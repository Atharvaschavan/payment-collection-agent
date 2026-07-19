"""Deterministic, templated natural-language generation.

Response text is template-based rather than LLM-generated so that facts the
user must be able to trust -- balances, transaction IDs, retry counts, error
reasons -- can never be hallucinated, omitted, or phrased inconsistently
between runs. This is what makes the agent's *output* deterministic even
though its *input understanding* is LLM-driven. See DESIGN.md.
"""
from decimal import Decimal


def _money(amount: Decimal) -> str:
    return f"₹{amount:,.2f}"


def _attempts_remaining_suffix(remaining_attempts: int, max_attempts: int) -> str:
    # Explicitly states the total limit (not just a countdown), so the user
    # is told the full retry policy the moment it becomes relevant -- e.g.
    # "(2 of 3 attempts remaining)" rather than just "(2 attempts left)".
    return f"({remaining_attempts} of {max_attempts} attempts remaining)"


GREETING_PREFIX = "Hello! "
INVALID_DATE_NOTICE = (
    "That doesn't look like a real calendar date, so I couldn't use it. "
)


def ask_for_account_id(already_greeted: bool = False) -> str:
    if already_greeted:
        return "Could you share your account ID to get started?"
    return "Please share your account ID to get started."


def invalid_account_id_format() -> str:
    return (
        "I couldn't quite make out an account ID there. Account IDs look "
        'like "ACC1001" -- could you share yours?'
    )


def account_not_found(remaining_attempts: int, max_attempts: int) -> str:
    return (
        "I couldn't find an account with that ID. Could you double-check "
        f"it? {_attempts_remaining_suffix(remaining_attempts, max_attempts)}"
    )


def account_lookup_exhausted() -> str:
    return (
        "I still can't find an account matching what you've provided, so "
        "I'm unable to continue. Please double-check your account ID and "
        "start a new conversation, or contact support for help."
    )


def ask_for_identity(just_arrived: bool = False) -> str:
    prefix = "Got it. " if just_arrived else ""
    return (
        prefix + "Could you please confirm your full name, and either your "
        "date of birth, the last 4 digits of your Aadhaar, or your pincode?"
    )


def ask_for_name_only() -> str:
    return "Thanks. Could you also confirm your full name?"


def ask_for_secondary_factor() -> str:
    return (
        "Thanks. Could you verify your date of birth, Aadhaar last 4 "
        "digits, or pincode?"
    )


def identity_mismatch_retry(remaining_attempts: int, max_attempts: int) -> str:
    return (
        "That doesn't match our records. Please double-check and provide "
        "your full name along with your date of birth, Aadhaar last 4 "
        f"digits, or pincode. {_attempts_remaining_suffix(remaining_attempts, max_attempts)}"
    )


def identity_exhausted() -> str:
    return (
        "I wasn't able to verify your identity after several attempts, so "
        "for your security I have to close this session here. Please "
        "contact support if you'd like to try again."
    )


def verified_share_balance(name: str, balance: Decimal) -> str:
    return (
        f"Identity verified. Your outstanding balance is {_money(balance)}. "
        "How much would you like to pay?"
    )


def no_balance_due(name: str, balance: Decimal) -> str:
    return (
        f"Identity verified. Good news, {name} -- your outstanding balance "
        f"is already {_money(balance)}, so there's nothing to pay right now. "
        "Have a great day!"
    )


def ask_amount(balance: Decimal) -> str:
    return (
        f"How much would you like to pay towards your {_money(balance)} "
        "balance? You can pay the full amount or a partial amount."
    )


def invalid_amount(reason: str) -> str:
    return f"{reason} Could you provide a valid amount?"


def amount_exceeds_balance(balance: Decimal) -> str:
    return (
        "That's more than your outstanding balance of "
        f"{_money(balance)}. Could you provide an amount at or below that?"
    )


def ask_card_details(missing_fields) -> str:
    return "Great. Could you share your " + ", ".join(missing_fields) + "?"


CARD_FIELD_MESSAGES = {
    "invalid_card": "That card number doesn't look valid. Could you re-enter it?",
    "invalid_cvv": "That CVV doesn't look right for this card. Could you re-enter it?",
    "invalid_expiry": "That expiry date looks invalid or already expired. Could you re-enter it?",
}


def invalid_card_field(reason: str, remaining_attempts: int, max_attempts: int) -> str:
    base = CARD_FIELD_MESSAGES.get(
        reason, "That card detail doesn't look valid. Could you re-enter it?"
    )
    return f"{base} {_attempts_remaining_suffix(remaining_attempts, max_attempts)}"


PAYMENT_ERROR_TEXT = {
    "invalid_card": "the card number appears to be invalid",
    "invalid_cvv": "the CVV appears to be invalid for this card",
    "invalid_expiry": "the card's expiry date appears invalid or expired",
    "invalid_amount": "the amount wasn't accepted by the payment processor",
    "account_not_found": "your account could no longer be located",
    # Observed live from the real sandbox API for a bad CVV or an expired
    # card -- a generic catch-all, not one of the assignment's documented
    # per-field codes. See RETRYABLE_CARD_ERRORS in orchestrator.py.
    "invalid_args": "one or more of your card details appear to be invalid",
}


def _error_text(error_code: str) -> str:
    return PAYMENT_ERROR_TEXT.get(error_code, "an unexpected error occurred")


def payment_failed_retryable(error_code: str, remaining_attempts: int, max_attempts: int) -> str:
    return (
        f"Your payment couldn't be processed because {_error_text(error_code)}. "
        f"Could you provide corrected card details? "
        f"{_attempts_remaining_suffix(remaining_attempts, max_attempts)}"
    )


def insufficient_balance_retry(balance: Decimal, remaining_attempts: int, max_attempts: int) -> str:
    return (
        f"That amount exceeds your outstanding balance of {_money(balance)}. "
        f"Could you provide a smaller amount? "
        f"{_attempts_remaining_suffix(remaining_attempts, max_attempts)}"
    )


def payment_exhausted(error_code: str) -> str:
    return (
        f"Your payment still couldn't be processed ({_error_text(error_code)}), "
        "and we've reached the retry limit. I have to close this session -- "
        "please try again later or contact support."
    )


def payment_terminal_failure(error_code: str) -> str:
    return (
        f"Your payment couldn't be processed because {_error_text(error_code)}. "
        "This isn't something we can fix by retrying right now, so I have "
        "to close this session. Please contact support for help."
    )


def network_error_retry() -> str:
    return (
        "Sorry, I couldn't reach the payment service just now. Could you "
        "confirm your card details again so I can retry?"
    )


def payment_success(name: str, amount: Decimal, transaction_id: str, last4: str) -> str:
    return (
        f"Payment successful! {_money(amount)} was charged to your card "
        f"ending in {last4}. Your transaction ID is {transaction_id}.\n\n"
        f"Recap: hi {name}, we verified your identity and processed a "
        f"payment of {_money(amount)} successfully (transaction ID "
        f"{transaction_id}). Thanks, and have a great day!"
    )


def cancelled_message() -> str:
    return "No problem -- I've cancelled this session. Have a great day!"


def decline_repeat_request() -> str:
    return (
        "For security reasons, I'm not able to repeat identifying "
        "information back to you once it's been provided. If you need to "
        "confirm your account ID or other details, please check your own "
        "records."
    )


def closed_message() -> str:
    return (
        "This conversation has ended. Please start a new session if you'd "
        "like to make another payment."
    )


def extraction_error() -> str:
    return "Sorry, I had trouble understanding that. Could you please rephrase?"


def extraction_uncertain() -> str:
    return (
        "I want to make sure I get your details exactly right before "
        "checking them. Could you clearly restate your full name along "
        "with your date of birth, Aadhaar last 4 digits, or pincode?"
    )


def account_switch_prompt() -> str:
    return "No problem -- let's start over with a different account. Please share the new account ID."
