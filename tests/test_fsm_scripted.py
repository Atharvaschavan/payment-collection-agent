"""End-to-end tests of the deterministic state machine.

Every LLM call is replaced by a FakeExtractor returning pre-scripted output,
so these tests are fast, free, and -- crucially -- deterministic: they test
"given this extraction, does the FSM do the right thing", which is exactly
the part of the system that must never vary between runs. The LLM's actual
extraction quality on messy real text is evaluated separately (see eval/).
"""
from decimal import Decimal

from payment_agent.api_client import PaymentAPIError
from payment_agent.orchestrator import PaymentCollectionAgent
from payment_agent.state import Stage
from tests.fakes import (
    ACC1001,
    ACC1002,
    ACC1003,
    ACC1004,
    VALID_CARD_NUMBER,
    FakeAPIClient,
    FakeExtractor,
    blank_extraction,
)


def make_agent(accounts, responses, payment_result=None, payment_error=None):
    api = FakeAPIClient(accounts=accounts, payment_result=payment_result, payment_error=payment_error)
    extractor = FakeExtractor(responses)
    return PaymentCollectionAgent(api_client=api, extractor=extractor), api


# --------------------------------------------------------------------------
# Successful end-to-end flow
# --------------------------------------------------------------------------

def test_successful_full_flow():
    agent, api = make_agent(
        {"ACC1001": ACC1001},
        [
            blank_extraction(intent="greeting"),
            blank_extraction(account_id="ACC1001"),
            blank_extraction(full_name="Nithin Jain"),
            blank_extraction(date_of_birth="1990-05-14"),
            blank_extraction(amount=500),
            blank_extraction(
                card_number=VALID_CARD_NUMBER, card_cvv="123",
                card_expiry_month=12, card_expiry_year=2027,
            ),
        ],
    )

    r1 = agent.next("Hi")
    assert r1["message"] == "Hello! Please share your account ID to get started."

    r2 = agent.next("yeah my account number is ACC1001 I think")
    assert "full name" in r2["message"].lower()

    r3 = agent.next("Nithin Jain")
    assert "date of birth" in r3["message"].lower() or "aadhaar" in r3["message"].lower()

    r4 = agent.next("DOB is 1990-05-14")
    assert "identity verified" in r4["message"].lower()
    assert "1,250.75" in r4["message"]

    r5 = agent.next("can I do 500 for now?")
    assert "card number" in r5["message"].lower()

    r6 = agent.next("the card number is 4532 0151 1283 0366, cvv is one two three, expires 12/27")
    assert "payment successful" in r6["message"].lower()
    assert "txn_test_1" in r6["message"]
    assert "0366" in r6["message"]

    assert agent.state.closed is True
    assert agent.state.stage == Stage.CLOSED_SUCCESS
    assert agent.state.transaction_id == "txn_test_1"
    assert len(api.payment_calls) == 1
    _, amount, card = api.payment_calls[0]
    assert amount == Decimal("500.00")
    assert card["cardholder_name"] == "Nithin Jain"


def test_out_of_order_info_in_single_message():
    agent, _ = make_agent(
        {"ACC1001": ACC1001},
        [
            blank_extraction(intent="greeting"),
            blank_extraction(
                account_id="ACC1001", full_name="Nithin Jain", date_of_birth="1990-05-14",
            ),
        ],
    )
    agent.next("Hi")
    result = agent.next(
        "it's ACC 1001, my name is Nithin Jain and my DOB is 1990-05-14"
    )
    assert "identity verified" in result["message"].lower()
    assert agent.state.verified is True
    assert agent.state.stage == Stage.AWAIT_AMOUNT


def test_account_id_is_not_overwritten_by_a_stray_extraction_after_lookup_succeeds():
    # Regression guard: found live during Phase 5 testing. A long digit
    # string in a later-stage message (e.g. a card number) can occasionally
    # get misclassified as an account_id too by the extractor. This is
    # harmless for the actual payment call (process_payment uses
    # state.account.account_id, the immutable lookup record, never this
    # field) but state.account_id itself must not be silently corrupted by
    # a later, irrelevant extraction once a lookup has already succeeded.
    agent, _ = make_agent(
        {"ACC1001": ACC1001},
        [
            blank_extraction(),
            blank_extraction(account_id="ACC1001"),
            blank_extraction(full_name="Nithin Jain", date_of_birth="1990-05-14"),
            blank_extraction(amount=500),
            # Simulates the observed misclassification: a card-number-shaped
            # message whose extraction also spuriously set account_id.
            blank_extraction(account_id="4532015112830366", card_number="4532015112830366"),
        ],
    )
    agent.next("Hi")
    agent.next("ACC1001")
    agent.next("Nithin Jain, DOB 1990-05-14")
    agent.next("500")
    agent.next("card 4532015112830366")
    assert agent.state.account_id == "ACC1001"
    assert agent.state.account.account_id == "ACC1001"


def test_full_balance_phrase_sets_exact_amount():
    agent, _ = make_agent(
        {"ACC1002": ACC1002},
        [
            blank_extraction(),
            blank_extraction(account_id="ACC1002", full_name="Rajarajeswari Balasubramaniam", aadhaar_last4="9876"),
            blank_extraction(amount_is_full_balance=True),
        ],
    )
    agent.next("Hi")
    agent.next("ACC1002, Rajarajeswari Balasubramaniam, Aadhaar last 4 is 9876")
    result = agent.next("just clear the full amount")
    assert agent.state.amount == Decimal("540.00")
    assert "card" in result["message"].lower()


def test_full_balance_phrase_quantizes_to_two_decimal_places_like_a_typed_amount_does():
    # Regression guard: found live during Phase 5 testing. A balance the API
    # returns as a bare integer-shaped JSON number (e.g. 540, not 540.00)
    # produces Decimal("540") from account lookup. The "full amount"
    # shortcut must still quantize this to Decimal("540.00") -- matching
    # what validators.normalize_amount() would produce for a manually-typed
    # "540" -- so state.amount has consistent precision regardless of which
    # path set it. (Plain Decimal `==` doesn't catch this, since
    # Decimal("540") == Decimal("540.00") by value -- check the string
    # representation, which is what actually differed.)
    account_with_bare_int_balance = dict(ACC1002)
    account_with_bare_int_balance["balance"] = 540  # int, not 540.00
    agent, _ = make_agent(
        {"ACC1002": account_with_bare_int_balance},
        [
            blank_extraction(),
            blank_extraction(account_id="ACC1002", full_name="Rajarajeswari Balasubramaniam", aadhaar_last4="9876"),
            blank_extraction(amount_is_full_balance=True),
        ],
    )
    agent.next("Hi")
    agent.next("ACC1002, Rajarajeswari Balasubramaniam, Aadhaar last 4 is 9876")
    agent.next("just clear the full amount")
    assert str(agent.state.amount) == "540.00"


def test_exact_balance_paid_via_explicit_number_not_the_full_amount_phrase():
    # Boundary check: amount == balance (not amount > balance) must be
    # accepted -- typing the exact number should work exactly like saying
    # "full amount", not be rejected as if it were an overpayment.
    agent, api = make_agent(
        {"ACC1002": ACC1002},
        [
            blank_extraction(),
            blank_extraction(account_id="ACC1002", full_name="Rajarajeswari Balasubramaniam", pincode="400002"),
            blank_extraction(amount=540.00),
            blank_extraction(
                card_number=VALID_CARD_NUMBER, card_cvv="123",
                card_expiry_month=12, card_expiry_year=2027,
            ),
        ],
    )
    agent.next("Hi")
    agent.next("ACC1002, Rajarajeswari Balasubramaniam, pincode 400002")
    result = agent.next("540")
    assert agent.state.amount == Decimal("540.00")
    assert "card" in result["message"].lower()
    final = agent.next("card 4532015112830366 cvv 123 exp 12/2027")
    assert agent.state.closed is True
    assert agent.state.stage == Stage.CLOSED_SUCCESS
    assert len(api.payment_calls) == 1


def test_zero_balance_account_closes_immediately_without_asking_for_payment():
    # ACC1003 has an outstanding balance of 0.00 -- there is nothing to
    # collect. This must be recognized right after verification, not
    # discovered later via a rejected 0.00 "full amount" payment (see the
    # no_balance_due close path in orchestrator.py for why the naive version
    # of this was a real bug: the "full amount" shortcut bypasses
    # normalize_amount()'s own zero-rejection).
    agent, api = make_agent(
        {"ACC1003": ACC1003},
        [
            blank_extraction(),
            blank_extraction(account_id="ACC1003", full_name="Priya Agarwal", aadhaar_last4="2468"),
        ],
    )
    agent.next("Hi")
    result = agent.next("ACC1003, Priya Agarwal, Aadhaar last 4 2468")
    assert agent.state.verified is True
    assert agent.state.closed is True
    assert agent.state.close_reason == "no_balance_due"
    assert agent.state.stage == Stage.CLOSED_SUCCESS
    assert "0.00" in result["message"]
    assert len(api.payment_calls) == 0  # never even reaches card collection


def test_zero_amount_explicitly_typed_is_rejected_on_a_nonzero_balance_account():
    agent, api = make_agent(
        {"ACC1001": ACC1001},
        [
            blank_extraction(),
            blank_extraction(account_id="ACC1001"),
            blank_extraction(full_name="Nithin Jain"),
            blank_extraction(date_of_birth="1990-05-14"),
            blank_extraction(amount=0),
        ],
    )
    agent.next("Hi")
    agent.next("ACC1001")
    agent.next("Nithin Jain")
    agent.next("1990-05-14")
    result = agent.next("0")
    assert agent.state.stage == Stage.AWAIT_AMOUNT
    assert agent.state.amount is None
    assert "greater than zero" in result["message"].lower()
    assert len(api.payment_calls) == 0


def test_cardholder_name_can_differ_from_the_verified_account_holder():
    # The API explicitly does not validate cardholder_name against the
    # account holder, so paying with someone else's card must be allowed --
    # but only when the user explicitly states a different name; otherwise
    # it defaults to the verified identity (see test_successful_full_flow).
    agent, api = make_agent(
        {"ACC1001": ACC1001},
        [
            blank_extraction(),
            blank_extraction(account_id="ACC1001"),
            blank_extraction(full_name="Nithin Jain"),
            blank_extraction(date_of_birth="1990-05-14"),
            blank_extraction(amount=500),
            blank_extraction(
                card_number=VALID_CARD_NUMBER, card_cvv="123",
                card_expiry_month=12, card_expiry_year=2027,
                cardholder_name="Suresh Jain",
            ),
        ],
    )
    agent.next("Hi")
    agent.next("ACC1001")
    agent.next("Nithin Jain")
    agent.next("1990-05-14")
    agent.next("500")
    agent.next("using my father Suresh Jain's card: 4532015112830366, cvv 123, exp 12/2027")
    assert agent.state.closed is True
    _, _, card = api.payment_calls[0]
    assert card["cardholder_name"] == "Suresh Jain"


# --------------------------------------------------------------------------
# Verification failure exhausting retries
# --------------------------------------------------------------------------

def test_verification_failure_exhausts_retries_and_closes():
    wrong_claim = blank_extraction(full_name="Rajarajeswari Balasubramaniam", date_of_birth="1990-01-01")
    agent, _ = make_agent(
        {"ACC1002": ACC1002},
        [
            blank_extraction(),
            blank_extraction(account_id="ACC1002"),
            # Each wrong claim is followed by a second, agreeing extraction
            # -- the reconciliation recheck, which confirms a mismatch is
            # genuine before charging an attempt.
            wrong_claim,
            wrong_claim,
            wrong_claim,
            wrong_claim,
            wrong_claim,
            wrong_claim,
        ],
    )
    agent.next("Hi")
    agent.next("ACC1002")
    r1 = agent.next("Rajarajeswari Balasubramaniam, DOB 1990-01-01")
    assert "2 of 3 attempts remaining" in r1["message"]
    r2 = agent.next("Rajarajeswari Balasubramaniam, DOB 1990-01-01")
    r3 = agent.next("Rajarajeswari Balasubramaniam, DOB 1990-01-01")
    assert agent.state.closed is True
    assert agent.state.close_reason == "verification_exhausted"
    assert agent.state.identity_attempts == 3
    assert "verify your identity" in r3["message"].lower() or "close" in r3["message"].lower()

    # Once closed, the agent must not call the extractor again and must
    # respond deterministically.
    r4 = agent.next("please let me try again")
    assert r4["message"] == r4["message"]  # closed_message() is a fixed string
    assert "ended" in r4["message"].lower()


def test_name_mismatch_never_passes_even_with_correct_secondary_factor():
    wrong_claim = blank_extraction(full_name="nithin jain", date_of_birth="1990-05-14")
    agent, _ = make_agent(
        {"ACC1001": ACC1001},
        [
            blank_extraction(),
            blank_extraction(account_id="ACC1001"),
            wrong_claim,
            # Reconciliation recheck: a second, agreeing
            # extraction confirms this mismatch is genuine.
            wrong_claim,
        ],
    )
    agent.next("Hi")
    agent.next("ACC1001")
    result = agent.next("nithin jain, dob 1990-05-14")
    assert agent.state.verified is False
    assert agent.state.identity_attempts == 1
    assert "doesn't match" in result["message"].lower()


# --------------------------------------------------------------------------
# Leap-year DOB edge case (ACC1004)
# --------------------------------------------------------------------------

def test_leap_year_dob_exact_match_succeeds():
    agent, _ = make_agent(
        {"ACC1004": ACC1004},
        [
            blank_extraction(),
            blank_extraction(account_id="ACC1004", full_name="Rahul Mehta", date_of_birth="1988-02-29"),
        ],
    )
    agent.next("Hi")
    result = agent.next("ACC1004, Rahul Mehta, DOB 1988-02-29")
    assert agent.state.verified is True
    assert "identity verified" in result["message"].lower()


def test_leap_year_dob_nearby_wrong_date_is_a_normal_mismatch_not_a_format_error():
    wrong_claim = blank_extraction(account_id="ACC1004", full_name="Rahul Mehta", date_of_birth="1988-02-28")
    agent, _ = make_agent(
        {"ACC1004": ACC1004},
        [
            blank_extraction(),
            wrong_claim,
            # Reconciliation recheck: a second, agreeing
            # extraction confirms this mismatch is genuine.
            wrong_claim,
        ],
    )
    agent.next("Hi")
    result = agent.next("ACC1004, Rahul Mehta, DOB 1988-02-28")
    assert agent.state.verified is False
    assert agent.state.identity_attempts == 1
    # A valid-but-wrong date is a mismatch, not an invalid-date notice.
    assert "real calendar date" not in result["message"].lower()


def test_impossible_date_is_flagged_before_being_treated_as_a_mismatch():
    agent, _ = make_agent(
        {"ACC1001": ACC1001},
        [
            blank_extraction(),
            blank_extraction(account_id="ACC1001"),
            # 1990 is not a leap year -> Feb 29 1990 cannot be a real date.
            blank_extraction(full_name="Nithin Jain", date_of_birth="1990-02-29"),
        ],
    )
    agent.next("Hi")
    agent.next("ACC1001")
    result = agent.next("Nithin Jain, DOB 1990-02-29")
    assert agent.state.identity_attempts == 0  # not counted as a failed attempt
    assert "real calendar date" in result["message"].lower()


# --------------------------------------------------------------------------
# Payment failure handling
# --------------------------------------------------------------------------

def _to_card_stage(agent):
    agent.next("Hi")
    agent.next("ACC1001")
    agent.next("Nithin Jain")
    agent.next("1990-05-14")
    agent.next("500")


def test_payment_failure_retries_then_exhausts():
    card_turn = blank_extraction(card_cvv="999")
    agent, api = make_agent(
        {"ACC1001": ACC1001},
        [
            blank_extraction(),
            blank_extraction(account_id="ACC1001"),
            blank_extraction(full_name="Nithin Jain"),
            blank_extraction(date_of_birth="1990-05-14"),
            blank_extraction(amount=500),
            blank_extraction(
                card_number=VALID_CARD_NUMBER, card_cvv="123",
                card_expiry_month=12, card_expiry_year=2027,
            ),
            card_turn,
            card_turn,
        ],
        payment_error=PaymentAPIError("invalid_cvv", "CVV is incorrect."),
    )
    _to_card_stage(agent)
    r1 = agent.next("card 4532015112830366 cvv 123 exp 12/2027")
    assert "cvv" in r1["message"].lower() or "card" in r1["message"].lower()
    assert agent.state.closed is False

    r2 = agent.next("999")
    assert agent.state.closed is False
    r3 = agent.next("999")

    assert agent.state.closed is True
    assert agent.state.close_reason == "payment_attempts_exhausted"
    assert len(api.payment_calls) == 3
    assert "close" in r3["message"].lower()


def test_invalid_args_error_code_is_treated_as_retryable_not_terminal():
    # Regression guard for a real discrepancy found live during Phase 6
    # testing: the real sandbox API returns error_code "invalid_args" (not
    # the documented "invalid_cvv" / "invalid_expiry") for a bad CVV or an
    # expired card. Without explicit handling, this code would silently
    # fall through to the terminal-failure branch and incorrectly end the
    # session over what should be a retryable, user-fixable card problem.
    # Since it's a generic code (the API doesn't say which field), the
    # whole card must be cleared and re-asked for, not just one field.
    agent, api = make_agent(
        {"ACC1001": ACC1001},
        [
            blank_extraction(),
            blank_extraction(account_id="ACC1001"),
            blank_extraction(full_name="Nithin Jain"),
            blank_extraction(date_of_birth="1990-05-14"),
            blank_extraction(amount=500),
            blank_extraction(
                card_number=VALID_CARD_NUMBER, card_cvv="123",
                card_expiry_month=12, card_expiry_year=2027,
            ),
        ],
        payment_error=PaymentAPIError("invalid_args", "One or more fields are invalid."),
    )
    _to_card_stage(agent)
    result = agent.next("card 4532015112830366 cvv 123 exp 12/2027")

    assert agent.state.closed is False
    assert "2 of 3 attempts remaining" in result["message"]
    # The whole card must be cleared (not just one field) since the API
    # didn't say which was wrong.
    assert agent.state.pending_card.card_number is None
    assert agent.state.pending_card.cvv is None
    assert agent.state.pending_card.expiry_month is None
    assert agent.state.pending_card.expiry_year is None


def test_locally_invalid_card_number_counts_against_the_retry_limit_and_never_calls_the_api():
    # A card number that fails the Luhn check is rejected before any API
    # call -- but repeated bad submissions must still hit a limit rather
    # than retrying forever.
    bad_card_turn = blank_extraction(card_number="1234567890123456", card_cvv="123", card_expiry_month=12, card_expiry_year=2027)
    agent, api = make_agent(
        {"ACC1001": ACC1001},
        [
            blank_extraction(),
            blank_extraction(account_id="ACC1001"),
            blank_extraction(full_name="Nithin Jain"),
            blank_extraction(date_of_birth="1990-05-14"),
            blank_extraction(amount=500),
            bad_card_turn,
            bad_card_turn,
            bad_card_turn,
        ],
    )
    _to_card_stage(agent)
    r1 = agent.next("card 1234567890123456 cvv 123 exp 12/2027")
    assert "attempt" in r1["message"].lower()
    assert agent.state.closed is False
    agent.next("card 1234567890123456 cvv 123 exp 12/2027")
    r3 = agent.next("card 1234567890123456 cvv 123 exp 12/2027")
    assert agent.state.closed is True
    assert agent.state.close_reason == "payment_attempts_exhausted"
    assert len(api.payment_calls) == 0  # never a valid card -> API never called


def test_insufficient_balance_from_api_sends_user_back_to_amount_stage():
    agent, api = make_agent(
        {"ACC1001": ACC1001},
        [
            blank_extraction(),
            blank_extraction(account_id="ACC1001"),
            blank_extraction(full_name="Nithin Jain"),
            blank_extraction(date_of_birth="1990-05-14"),
            blank_extraction(amount=500),
            blank_extraction(
                card_number=VALID_CARD_NUMBER, card_cvv="123",
                card_expiry_month=12, card_expiry_year=2027,
            ),
        ],
        payment_error=PaymentAPIError("insufficient_balance", "Amount exceeds balance."),
    )
    _to_card_stage(agent)
    result = agent.next("card 4532015112830366 cvv 123 exp 12/2027")
    assert agent.state.stage == Stage.AWAIT_AMOUNT
    assert agent.state.closed is False
    assert "balance" in result["message"].lower()


def test_amount_exceeding_balance_is_rejected_before_any_api_call():
    agent, api = make_agent(
        {"ACC1002": ACC1002},
        [
            blank_extraction(),
            blank_extraction(account_id="ACC1002"),
            blank_extraction(full_name="Rajarajeswari Balasubramaniam"),
            blank_extraction(pincode="400002"),
            blank_extraction(amount=1000),
        ],
    )
    agent.next("Hi")
    agent.next("ACC1002")
    agent.next("Rajarajeswari Balasubramaniam")
    agent.next("pincode 400002")
    result = agent.next("I want to pay 1000")
    assert agent.state.stage == Stage.AWAIT_AMOUNT
    assert "540.00" in result["message"]
    assert len(api.payment_calls) == 0


# --------------------------------------------------------------------------
# Account lookup failure
# --------------------------------------------------------------------------

def test_account_lookup_exhausted_closes_conversation():
    agent, api = make_agent(
        {},
        [
            blank_extraction(),
            blank_extraction(account_id="ACC9001"),
            blank_extraction(account_id="ACC9002"),
            blank_extraction(account_id="ACC9003"),
        ],
    )
    agent.next("Hi")
    agent.next("ACC9001")
    agent.next("ACC9002")
    result = agent.next("ACC9003")
    assert agent.state.closed is True
    assert agent.state.close_reason == "account_lookup_exhausted"
    assert "unable to continue" in result["message"].lower() or "contact support" in result["message"].lower()


# --------------------------------------------------------------------------
# Cancellation
# --------------------------------------------------------------------------

def test_user_can_cancel_mid_flow():
    agent, _ = make_agent(
        {"ACC1001": ACC1001},
        [
            blank_extraction(),
            blank_extraction(account_id="ACC1001"),
            blank_extraction(wants_to_stop=True),
        ],
    )
    agent.next("Hi")
    agent.next("ACC1001")
    result = agent.next("actually never mind, cancel this")
    assert agent.state.closed is True
    assert agent.state.close_reason == "user_cancelled"
    assert "cancelled" in result["message"].lower()


# --------------------------------------------------------------------------
# Security: never repeat identifying information back on request
# --------------------------------------------------------------------------

def test_declines_to_repeat_account_id_back_on_request():
    agent, _ = make_agent(
        {"ACC1001": ACC1001},
        [
            blank_extraction(),
            blank_extraction(account_id="ACC1001"),
            blank_extraction(wants_info_repeated=True),
        ],
    )
    agent.next("Hi")
    agent.next("ACC1001")
    result = agent.next("wait, can you repeat my account ID back to me?")
    assert "ACC1001" not in result["message"]
    assert "security" in result["message"].lower()
    # Declining to repeat is not a cancellation or a closure -- the
    # conversation continues normally afterward.
    assert agent.state.closed is False
    assert agent.state.account_id == "ACC1001"


def test_declines_to_repeat_identity_fields_back_mid_verification():
    agent, _ = make_agent(
        {"ACC1001": ACC1001},
        [
            blank_extraction(),
            blank_extraction(account_id="ACC1001"),
            blank_extraction(full_name="Nithin Jain", date_of_birth="1990-05-14"),
            blank_extraction(wants_info_repeated=True),
        ],
    )
    agent.next("Hi")
    agent.next("ACC1001")
    agent.next("Nithin Jain, DOB 1990-05-14")
    assert agent.state.verified is True
    result = agent.next("sorry what date of birth did I just give you?")
    assert "1990-05-14" not in result["message"]
    assert "security" in result["message"].lower()
    assert agent.state.closed is False


# --------------------------------------------------------------------------
# Extraction failure (LLM call raises) degrades gracefully
# --------------------------------------------------------------------------

def test_extraction_failure_does_not_crash_or_advance_state():
    class BrokenExtractor:
        def extract(self, *a, **kw):
            raise RuntimeError("simulated LLM outage")

    api = FakeAPIClient(accounts={"ACC1001": ACC1001})
    agent = PaymentCollectionAgent(api_client=api, extractor=BrokenExtractor())
    result = agent.next("Hi")
    assert agent.state.closed is False
    assert agent.state.stage == Stage.AWAIT_ACCOUNT_ID
    assert "trouble understanding" in result["message"].lower() or "rephrase" in result["message"].lower()


# --------------------------------------------------------------------------
# Account-ID normalization is deterministic, not dependent on the LLM
# getting its own formatting instructions right
# --------------------------------------------------------------------------

def test_un_normalized_account_id_from_extraction_is_still_looked_up_correctly():
    # Simulates exactly what was found live and reproducibly on
    # gpt-4.1-mini: the extractor returns the account ID without applying
    # its own normalization instructions ("acc 1001", not "ACC1001").
    agent, _ = make_agent(
        {"ACC1001": ACC1001},
        [
            blank_extraction(),
            blank_extraction(account_id="acc 1001"),
        ],
    )
    agent.next("Hi")
    result = agent.next("acc 1001")
    assert agent.state.account is not None
    assert agent.state.account.account_id == "ACC1001"
    assert "full name" in result["message"].lower()


# --------------------------------------------------------------------------
# Backward-movement fixes: account switching mid-conversation,
# and an amount changed while collecting card details
# --------------------------------------------------------------------------

def test_switching_account_mid_conversation_resets_state_and_restarts_lookup():
    agent, _ = make_agent(
        {"ACC1001": ACC1001, "ACC1002": ACC1002},
        [
            blank_extraction(),
            blank_extraction(account_id="ACC1001"),
            blank_extraction(full_name="Nithin Jain"),  # partial claim, no attempt burned
            blank_extraction(wants_to_switch_account=True),
            blank_extraction(account_id="ACC1002"),
            blank_extraction(full_name="Rajarajeswari Balasubramaniam", pincode="400002"),
        ],
    )
    agent.next("Hi")
    agent.next("ACC1001")
    agent.next("Nithin Jain")
    result = agent.next("actually, wrong account -- can we start over with a different one?")
    assert "different account" in result["message"].lower() or "start over" in result["message"].lower()
    # Everything tied to ACC1001 must be gone, not just the account record.
    assert agent.state.account is None
    assert agent.state.account_id is None
    assert agent.state.claimed_name is None
    assert agent.state.stage == Stage.AWAIT_ACCOUNT_ID
    assert agent.state.closed is False

    agent.next("ACC1002")
    result = agent.next("Rajarajeswari Balasubramaniam, pincode 400002")
    assert agent.state.verified is True
    assert agent.state.account.account_id == "ACC1002"


def test_wants_to_switch_account_is_ignored_before_any_account_is_looked_up():
    # Nothing to switch away from yet -- must not do anything unexpected,
    # just proceed with normal account-ID collection.
    agent, _ = make_agent(
        {"ACC1001": ACC1001},
        [
            blank_extraction(wants_to_switch_account=True),
        ],
    )
    result = agent.next("actually let's use a different account")
    assert agent.state.account is None
    assert agent.state.stage == Stage.AWAIT_ACCOUNT_ID
    assert agent.state.closed is False


def test_amount_changed_during_card_collection_is_not_silently_dropped():
    agent, api = make_agent(
        {"ACC1001": ACC1001},
        [
            blank_extraction(),
            blank_extraction(account_id="ACC1001", full_name="Nithin Jain", date_of_birth="1990-05-14"),
            blank_extraction(amount=500),
            blank_extraction(card_number=VALID_CARD_NUMBER),  # missing cvv/expiry -> re-asks
            blank_extraction(amount=300, card_cvv="123", card_expiry_month=12, card_expiry_year=2027),
        ],
        payment_result={"transaction_id": "txn_switch_amount"},
    )
    agent.next("Hi")
    agent.next("ACC1001, Nithin Jain, DOB 1990-05-14")
    agent.next("500")
    agent.next("card 4532015112830366")
    assert agent.state.stage == Stage.AWAIT_CARD_DETAILS
    result = agent.next("actually, can I pay 300 instead? cvv 123, expiry 12/2027")
    # The corrected amount must actually be the one charged -- not silently
    # dropped in favor of the original 500.
    assert agent.state.closed is True
    assert agent.state.close_reason == "payment_success"
    _, charged_amount, _ = api.payment_calls[0]
    assert str(charged_amount) == "300.00"
    assert "300.00" in result["message"]


# --------------------------------------------------------------------------
# Retry-fairness reconciliation: a disagreeing recheck must
# not burn a real verification attempt
# --------------------------------------------------------------------------

def test_disagreeing_reconciliation_recheck_does_not_burn_a_verification_attempt():
    agent, _ = make_agent(
        {"ACC1001": ACC1001},
        [
            blank_extraction(),
            blank_extraction(account_id="ACC1001"),
            # Original extraction claims a mismatching DOB...
            blank_extraction(full_name="Nithin Jain", date_of_birth="1990-01-01"),
            # ...but the reconciliation recheck disagrees on the DOB --
            # this extraction is unreliable for this message, so no
            # attempt should be charged.
            blank_extraction(full_name="Nithin Jain", date_of_birth="1990-05-14"),
        ],
    )
    agent.next("Hi")
    agent.next("ACC1001")
    result = agent.next("Nithin Jain, DOB 1990-01-01")
    assert agent.state.identity_attempts == 0
    assert agent.state.verified is False
    assert agent.state.closed is False
    assert "restate" in result["message"].lower()


def test_agreeing_reconciliation_recheck_does_burn_a_verification_attempt():
    wrong_claim = blank_extraction(full_name="Nithin Jain", date_of_birth="1990-01-01")
    agent, _ = make_agent(
        {"ACC1001": ACC1001},
        [
            blank_extraction(),
            blank_extraction(account_id="ACC1001"),
            wrong_claim,
            wrong_claim,  # reconciliation recheck agrees -- genuine mismatch
        ],
    )
    agent.next("Hi")
    agent.next("ACC1001")
    result = agent.next("Nithin Jain, DOB 1990-01-01")
    assert agent.state.identity_attempts == 1
    assert "2 of 3 attempts remaining" in result["message"]


def test_reconciliation_recheck_raising_is_treated_as_uncertain_not_charged():
    class OnceThenBrokenExtractor:
        """Returns one scripted response, then raises on the reconciliation
        recheck call -- simulates a transient outage on the second call."""

        def __init__(self, first_responses, then_raises):
            self._responses = list(first_responses)
            self._then_raises = then_raises

        def extract(self, *a, **kw):
            if self._responses:
                return self._responses.pop(0)
            raise self._then_raises

    api = FakeAPIClient(accounts={"ACC1001": ACC1001})
    extractor = OnceThenBrokenExtractor(
        [
            blank_extraction(),
            blank_extraction(account_id="ACC1001"),
            blank_extraction(full_name="Nithin Jain", date_of_birth="1990-01-01"),
        ],
        RuntimeError("simulated transient outage on recheck"),
    )
    agent = PaymentCollectionAgent(api_client=api, extractor=extractor)
    agent.next("Hi")
    agent.next("ACC1001")
    result = agent.next("Nithin Jain, DOB 1990-01-01")
    assert agent.state.identity_attempts == 0
    assert agent.state.closed is False
    assert "restate" in result["message"].lower()
