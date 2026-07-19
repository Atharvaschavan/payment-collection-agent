"""The conversation state machine.

Architecture in one paragraph: every turn, the LLM extractor (extraction.py)
turns free text into structured slots; this module merges those slots into
ConversationState and then runs a deterministic state machine over them --
deciding when to call the two provided APIs, validating everything first
(validators.py), verifying identity with a strict exact-match comparison
(verification.py) that the LLM never sees or influences, and finally
rendering the reply from fixed templates (nlg.py) so nothing the user reads
is hallucinated. See DESIGN.md for the full writeup and the reasoning behind
this split.
"""
from decimal import Decimal
from typing import Optional

from . import config, nlg, validators, verification
from .api_client import PaymentAPIClient, PaymentAPIError
from .extraction import LLMExtractor
from .state import AccountRecord, ConversationState, Stage

# error_code values from POST /api/process-payment that are the user's to fix
# by re-entering a card field, as opposed to terminal failures.
#
# "invalid_args" is not in the assignment's documented error-code table, but
# was observed live against the real sandbox API: a wrong-length CVV and an
# expired card both return HTTP 400 with error_code "invalid_args" -- not
# the documented "invalid_cvv" / "invalid_expiry". Since client-side
# validation (validators.py) already rejects malformed CVV/expiry before
# any API call, this code should rarely if ever actually reach here in
# practice -- but if it does (e.g. a validation-rule mismatch this client
# doesn't anticipate), it must still be treated as retryable, not terminal:
# without this entry it would silently fall through to the terminal-failure
# branch below and incorrectly end the session over a fixable card detail.
RETRYABLE_CARD_ERRORS = {"invalid_card", "invalid_cvv", "invalid_expiry", "invalid_amount", "invalid_args"}


class PaymentCollectionAgent:
    """Implements the full greet -> lookup -> verify -> pay -> close flow.

    api_client / extractor are constructor-injectable so tests can supply
    fakes and exercise the state machine deterministically, without hitting
    the network or an LLM. See tests/fakes.py.
    """

    def __init__(
        self,
        api_client: Optional[PaymentAPIClient] = None,
        extractor: Optional[LLMExtractor] = None,
    ):
        self.api = api_client or PaymentAPIClient()
        self.extractor = extractor or LLMExtractor()
        self.state = ConversationState()

    # ------------------------------------------------------------------ #
    # Public interface
    # ------------------------------------------------------------------ #

    def next(self, user_input: str) -> dict:
        self.state.turn_count += 1

        if self.state.closed:
            return {"message": nlg.closed_message()}

        first_turn = self.state.turn_count == 1

        try:
            data = self.extractor.extract(
                transcript=self.state.transcript,
                latest_user_message=user_input,
                stage_hint=self.state.stage.value,
            )
        except Exception:
            message = nlg.extraction_error()
            self._record_turn(user_input, message)
            return {"message": message}

        self._merge_slots(data)

        if data.get("wants_to_stop"):
            message = nlg.cancelled_message()
            self._close_failure("user_cancelled")
            self._record_turn(user_input, message)
            return {"message": message}

        if data.get("wants_info_repeated"):
            # Security: never echo identifying information back on request,
            # regardless of stage. This is a hard short-circuit -- it never
            # reaches nlg templates that might otherwise interpolate
            # account_id, claimed identity fields, or card data.
            message = nlg.decline_repeat_request()
            self._record_turn(user_input, message)
            return {"message": message}

        if data.get("wants_to_switch_account") and self.state.account is not None:
            # The FSM is otherwise forward-only: once an
            # account is looked up, nothing lets the user redirect to a
            # different one. This is the one explicit, deliberate escape
            # hatch -- a full reset back to account lookup, rather than
            # silently dropping the request or forcing a total cancel.
            self._reset_for_account_switch()
            message = nlg.account_switch_prompt()
            self._record_turn(user_input, message)
            return {"message": message}

        if self.state.stage == Stage.AWAIT_CARD_DETAILS and (
            data.get("amount") is not None or data.get("amount_is_full_balance")
        ):
            # A new amount volunteered while collecting card details would
            # otherwise be merged into state and then never read again --
            # _handle_card() doesn't look at pending_amount_raw.
            # Bounce back to the amount stage so it's
            # actually validated; already-collected card fields are kept,
            # and _handle_amount() routes straight back into card
            # collection once the new amount is accepted.
            self.state.stage = Stage.AWAIT_AMOUNT

        message = self._route(first_turn, user_input)
        if first_turn:
            message = nlg.GREETING_PREFIX + message

        self._record_turn(user_input, message)
        return {"message": message}

    # ------------------------------------------------------------------ #
    # Slot merging (context management: never re-ask for what we have)
    # ------------------------------------------------------------------ #

    def _merge_slots(self, data: dict) -> None:
        # account_id is only actionable before a lookup has succeeded --
        # once self.state.account is populated, the authoritative account
        # ID lives on that immutable record (used for the actual payment
        # call), not this mutable field. Ignoring later account_id
        # extractions here guards against a real observed extraction
        # quirk: a long digit string in a later-stage message (e.g. a card
        # number) can occasionally get misclassified as an account_id too.
        # Harmless today (nothing reads this field past account lookup),
        # but not ignoring it would be a latent footgun for any future code
        # that does.
        if data.get("account_id") and self.state.account is None:
            self.state.account_id = validators.normalize_account_id(data["account_id"])

        if data.get("full_name"):
            self.state.claimed_name = data["full_name"]

        if data.get("date_of_birth"):
            if validators.parse_iso_date(data["date_of_birth"]):
                self.state.claimed_dob = data["date_of_birth"]
                self.state.invalid_date_notice = False
            else:
                self.state.invalid_date_notice = True

        if data.get("aadhaar_last4"):
            self.state.claimed_aadhaar_last4 = data["aadhaar_last4"]

        if data.get("pincode"):
            self.state.claimed_pincode = data["pincode"]

        if data.get("amount") is not None:
            self.state.pending_amount_raw = data["amount"]
        if data.get("amount_is_full_balance"):
            self.state.pending_amount_full_balance = True

        card = self.state.pending_card
        if data.get("card_number"):
            card.card_number = data["card_number"]
        if data.get("card_cvv"):
            card.cvv = data["card_cvv"]
        if data.get("card_expiry_month"):
            card.expiry_month = data["card_expiry_month"]
        if data.get("card_expiry_year"):
            card.expiry_year = data["card_expiry_year"]
        if data.get("cardholder_name"):
            card.cardholder_name = data["cardholder_name"]

    # ------------------------------------------------------------------ #
    # Routing
    # ------------------------------------------------------------------ #

    def _route(self, first_turn: bool, user_input: str) -> str:
        stage = self.state.stage
        if stage == Stage.AWAIT_ACCOUNT_ID:
            return self._handle_account_id(first_turn, user_input)
        if stage == Stage.AWAIT_IDENTITY:
            return self._handle_identity(user_input)
        if stage == Stage.AWAIT_AMOUNT:
            return self._handle_amount()
        if stage == Stage.AWAIT_CARD_DETAILS:
            return self._handle_card()
        return nlg.closed_message()  # defensive; closed states return earlier

    # ------------------------------------------------------------------ #
    # Stage handlers
    # ------------------------------------------------------------------ #

    def _handle_account_id(self, first_turn: bool, user_input: str) -> str:
        account_id = self.state.account_id
        if not account_id:
            return nlg.ask_for_account_id(already_greeted=not first_turn)

        if not validators.is_valid_account_id(account_id):
            self.state.account_id = None
            return nlg.invalid_account_id_format()

        try:
            record = self.api.lookup_account(account_id)
        except PaymentAPIError as exc:
            self.state.account_id = None
            if exc.error_code == "account_not_found":
                self.state.lookup_attempts += 1
                if self.state.lookup_attempts >= config.MAX_ACCOUNT_LOOKUP_ATTEMPTS:
                    self._close_failure("account_lookup_exhausted")
                    return nlg.account_lookup_exhausted()
                remaining = config.MAX_ACCOUNT_LOOKUP_ATTEMPTS - self.state.lookup_attempts
                return nlg.account_not_found(remaining, config.MAX_ACCOUNT_LOOKUP_ATTEMPTS)
            return nlg.network_error_retry()

        self.state.account = AccountRecord(
            account_id=record["account_id"],
            full_name=record["full_name"],
            dob=record["dob"],
            aadhaar_last4=record["aadhaar_last4"],
            pincode=record["pincode"],
            balance=Decimal(str(record["balance"])),
        )
        self.state.stage = Stage.AWAIT_IDENTITY
        # The user may have volunteered identity info in the same message
        # that contained the account ID -- resolve it now instead of
        # re-asking for what we already have (out-of-order handling).
        return self._handle_identity(user_input, just_arrived=True)

    def _handle_identity(self, user_input: str, just_arrived: bool = False) -> str:
        prefix = ""
        if self.state.invalid_date_notice:
            prefix = nlg.INVALID_DATE_NOTICE
            self.state.invalid_date_notice = False

        account = self.state.account
        outcome = verification.evaluate(
            account,
            self.state.claimed_name,
            self.state.claimed_dob,
            self.state.claimed_aadhaar_last4,
            self.state.claimed_pincode,
        )

        if outcome == verification.Outcome.SUCCESS:
            self.state.verified = True
            self.state.verified_name = self.state.claimed_name
            # An account with nothing owed (e.g. ACC1003, balance 0.00) has no
            # payment to collect. Don't ask "how much would you like to pay"
            # against a zero balance -- and critically, don't let the "full
            # amount" shortcut in _handle_amount bypass normalize_amount()'s
            # zero-amount rejection by resolving to a 0.00 payment. Recognize
            # this immediately and close cleanly instead.
            if account.balance <= 0:
                self._close_success_no_payment_needed()
                return prefix + nlg.no_balance_due(self.state.verified_name, account.balance)
            self.state.stage = Stage.AWAIT_AMOUNT
            return prefix + nlg.verified_share_balance(self.state.verified_name, account.balance)

        if outcome == verification.Outcome.NEED_BOTH:
            return prefix + nlg.ask_for_identity(just_arrived=just_arrived)
        if outcome == verification.Outcome.NEED_NAME:
            return prefix + nlg.ask_for_name_only()
        if outcome == verification.Outcome.NEED_SECONDARY:
            return prefix + nlg.ask_for_secondary_factor()

        # FAIL: a full claim (name + a secondary factor) was supplied and
        # didn't match. Before charging this against the retry limit,
        # confirm it isn't just a one-off flaky extraction:
        # re-run extraction once more on the same message and require
        # agreement. A single inconsistent LLM call should not cost the
        # user a real attempt when the mistake may well have been the
        # extractor's, not theirs.
        if not self._reconcile_identity_claim(user_input):
            self._clear_claimed_identity()
            return prefix + nlg.extraction_uncertain()

        # Counts as a retry attempt. Claims are cleared so a retry must be
        # a fresh, complete statement rather than silently reusing a stale
        # wrong value.
        self.state.identity_attempts += 1
        self._clear_claimed_identity()

        if self.state.identity_attempts >= config.MAX_VERIFICATION_ATTEMPTS:
            self._close_failure("verification_exhausted")
            return prefix + nlg.identity_exhausted()

        remaining = config.MAX_VERIFICATION_ATTEMPTS - self.state.identity_attempts
        return prefix + nlg.identity_mismatch_retry(remaining, config.MAX_VERIFICATION_ATTEMPTS)

    def _clear_claimed_identity(self) -> None:
        self.state.claimed_name = None
        self.state.claimed_dob = None
        self.state.claimed_aadhaar_last4 = None
        self.state.claimed_pincode = None

    def _reconcile_identity_claim(self, user_input: str) -> bool:
        """Guards against a single flaky LLM extraction silently burning a
        real verification attempt. Re-runs extraction once
        more on the exact same message and requires it to agree with what
        was already merged into state for this claim; if the two
        extractions disagree on any claimed field, the mismatch isn't
        trustworthy enough to charge against the user's limited attempts.

        Deliberately scoped to identity verification only -- this is
        where the concrete evidence of unfairness was observed (a correct
        DOB once misclassified as a mismatch, see EVALUATION.md).
        Account-lookup and card/amount fields don't have the same
        documented risk: account IDs are simple tokens, and card/amount
        fields are validated deterministically before ever costing an
        attempt, so an extraction miss there just re-prompts rather than
        silently charging anything.
        """
        try:
            recheck = self.extractor.extract(
                transcript=self.state.transcript,
                latest_user_message=user_input,
                stage_hint=self.state.stage.value,
            )
        except Exception:
            # If the recheck call itself fails, don't assume the original
            # extraction was trustworthy -- treat this turn as uncertain
            # rather than penalize the user for an outage.
            return False

        current = {
            "full_name": self.state.claimed_name,
            "date_of_birth": self.state.claimed_dob,
            "aadhaar_last4": self.state.claimed_aadhaar_last4,
            "pincode": self.state.claimed_pincode,
        }
        for field_name, current_value in current.items():
            recheck_value = recheck.get(field_name)
            if recheck_value and recheck_value != current_value:
                return False
        return True

    def _handle_amount(self) -> str:
        account = self.state.account
        balance = account.balance

        if self.state.pending_amount_full_balance:
            # Quantize to 2 decimal places for the same reason
            # normalize_amount() does below: the lookup API can return a
            # balance with fewer implied decimal places (e.g. a bare "540"
            # JSON literal), and state.amount should have consistent
            # precision regardless of whether it was set via "full amount"
            # or a manually-typed number.
            amount = balance.quantize(Decimal("0.01"))
        elif self.state.pending_amount_raw is not None:
            try:
                amount = validators.normalize_amount(self.state.pending_amount_raw)
            except validators.ValidationError as exc:
                self.state.pending_amount_raw = None
                self.state.pending_amount_full_balance = False
                return nlg.invalid_amount(str(exc))
        else:
            return nlg.ask_amount(balance)

        if amount > balance:
            self.state.pending_amount_raw = None
            self.state.pending_amount_full_balance = False
            return nlg.amount_exceeds_balance(balance)

        self.state.amount = amount
        self.state.pending_amount_raw = None
        self.state.pending_amount_full_balance = False
        self.state.stage = Stage.AWAIT_CARD_DETAILS
        # Card details may already have been volunteered earlier in the
        # conversation -- proceed immediately instead of re-asking.
        return self._handle_card()

    def _handle_card(self) -> str:
        card = self.state.pending_card
        if not card.cardholder_name:
            card.cardholder_name = self.state.verified_name

        missing = []
        if not card.card_number:
            missing.append("card number")
        if not card.cvv:
            missing.append("CVV")
        if not card.expiry_month or not card.expiry_year:
            missing.append("expiry date")
        if missing:
            return nlg.ask_card_details(missing)

        ok, reason = validators.validate_card_number(card.card_number)
        if not ok:
            card.card_number = None
            return self._reject_card_field(reason)

        ok, reason = validators.validate_cvv(card.cvv, card.card_number)
        if not ok:
            card.cvv = None
            return self._reject_card_field(reason)

        ok, reason = validators.validate_expiry(card.expiry_month, card.expiry_year)
        if not ok:
            card.expiry_month = None
            card.expiry_year = None
            return self._reject_card_field(reason)

        try:
            result = self.api.process_payment(
                self.state.account.account_id,
                self.state.amount,
                {
                    "cardholder_name": card.cardholder_name,
                    "card_number": card.card_number,
                    "cvv": card.cvv,
                    "expiry_month": card.expiry_month,
                    "expiry_year": card.expiry_year,
                },
            )
        except PaymentAPIError as exc:
            return self._handle_payment_error(exc)

        last4 = card.card_number[-4:]
        amount = self.state.amount
        name = self.state.verified_name
        self.state.transaction_id = result["transaction_id"]
        self._close_success()
        return nlg.payment_success(name, amount, result["transaction_id"], last4)

    def _reject_card_field(self, reason: str) -> str:
        """A card field failed *local* format validation (Luhn, CVV length,
        expiry) before any API call was made. This still counts against the
        shared payment-attempt limit -- otherwise a user (or a malformed
        automated caller) could resubmit an invalid card indefinitely with
        no cap, which "a sensible retry limit" is meant to prevent.
        """
        self.state.payment_attempts += 1
        if self.state.payment_attempts >= config.MAX_PAYMENT_ATTEMPTS:
            self._close_failure("payment_attempts_exhausted")
            return nlg.payment_exhausted(reason)
        remaining = config.MAX_PAYMENT_ATTEMPTS - self.state.payment_attempts
        return nlg.invalid_card_field(reason, remaining, config.MAX_PAYMENT_ATTEMPTS)

    def _handle_payment_error(self, exc: PaymentAPIError) -> str:
        self.state.payment_attempts += 1
        exhausted = self.state.payment_attempts >= config.MAX_PAYMENT_ATTEMPTS

        if exc.error_code in RETRYABLE_CARD_ERRORS:
            if exc.error_code == "invalid_card":
                self.state.pending_card.card_number = None
            elif exc.error_code == "invalid_cvv":
                self.state.pending_card.cvv = None
            elif exc.error_code == "invalid_expiry":
                self.state.pending_card.expiry_month = None
                self.state.pending_card.expiry_year = None
            elif exc.error_code == "invalid_amount":
                self.state.amount = None
                self.state.stage = Stage.AWAIT_AMOUNT
            elif exc.error_code == "invalid_args":
                # Generic code observed live for both bad CVV and expired
                # cards -- the API doesn't say which field, so clear the
                # whole card and have the user re-enter everything rather
                # than guess which single field to drop.
                self.state.pending_card.clear()

            if exhausted:
                self._close_failure("payment_attempts_exhausted")
                return nlg.payment_exhausted(exc.error_code)
            return nlg.payment_failed_retryable(
                exc.error_code,
                config.MAX_PAYMENT_ATTEMPTS - self.state.payment_attempts,
                config.MAX_PAYMENT_ATTEMPTS,
            )

        if exc.error_code == "insufficient_balance":
            self.state.amount = None
            self.state.stage = Stage.AWAIT_AMOUNT
            if exhausted:
                self._close_failure("payment_attempts_exhausted")
                return nlg.payment_exhausted(exc.error_code)
            return nlg.insufficient_balance_retry(
                self.state.account.balance,
                config.MAX_PAYMENT_ATTEMPTS - self.state.payment_attempts,
                config.MAX_PAYMENT_ATTEMPTS,
            )

        if exc.error_code == "network_error" and not exhausted:
            return nlg.network_error_retry()

        # account_not_found post-lookup, an unrecognized error, or a
        # network error that has exhausted its retries: terminal.
        self._close_failure("payment_terminal_error")
        return nlg.payment_terminal_failure(exc.error_code)

    # ------------------------------------------------------------------ #
    # Termination / bookkeeping
    # ------------------------------------------------------------------ #

    def _close_success(self) -> None:
        self.state.closed = True
        self.state.stage = Stage.CLOSED_SUCCESS
        self.state.close_reason = "payment_success"
        self.state.pending_card.clear()

    def _close_success_no_payment_needed(self) -> None:
        self.state.closed = True
        self.state.stage = Stage.CLOSED_SUCCESS
        self.state.close_reason = "no_balance_due"
        self.state.pending_card.clear()

    def _close_failure(self, reason: str) -> None:
        self.state.closed = True
        self.state.stage = Stage.CLOSED_FAILURE
        self.state.close_reason = reason
        self.state.pending_card.clear()

    def _reset_for_account_switch(self) -> None:
        """Handles a user explicitly wanting to restart with a different
        account mid-conversation. Clears everything tied to
        the OLD account -- lookup, identity, amount, card, and every retry
        counter -- and returns to the first stage, since a different
        account means a fresh verification and a fresh payment are both
        required regardless of anything already collected. Does not touch
        turn_count or transcript -- this is a redirect within the same
        conversation, not a new session.
        """
        self.state.account_id = None
        self.state.account = None
        self.state.lookup_attempts = 0
        self._clear_claimed_identity()
        self.state.invalid_date_notice = False
        self.state.verified = False
        self.state.verified_name = None
        self.state.identity_attempts = 0
        self.state.pending_amount_raw = None
        self.state.pending_amount_full_balance = False
        self.state.amount = None
        self.state.pending_card.clear()
        self.state.payment_attempts = 0
        self.state.stage = Stage.AWAIT_ACCOUNT_ID

    def _record_turn(self, user_input: str, agent_message: str) -> None:
        self.state.transcript.append({"role": "user", "content": user_input})
        self.state.transcript.append({"role": "assistant", "content": agent_message})
        overflow = len(self.state.transcript) - config.MAX_HISTORY_MESSAGES_FOR_EXTRACTION
        if overflow > 0:
            del self.state.transcript[:overflow]
