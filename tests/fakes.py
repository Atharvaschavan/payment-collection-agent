"""Test doubles for the FSM tests.

These let tests/test_fsm_scripted.py exercise the deterministic state machine
in orchestrator.py exactly, without depending on network access, an
OPENAI_API_KEY, or the inherent (small) variance of a real LLM call. The
LLM's actual extraction quality is instead evaluated separately in eval/,
against the real model and real API -- see EVALUATION.md for why the two are
split.
"""
from payment_agent.api_client import PaymentAPIError


def blank_extraction(**overrides) -> dict:
    """A fully-null extraction result with the given fields overridden.

    Mirrors exactly what LLMExtractor.extract() returns, so scripted fakes
    stay honest about the real return shape.
    """
    base = {
        "intent": "provide_info",
        "account_id": None,
        "full_name": None,
        "date_of_birth": None,
        "aadhaar_last4": None,
        "pincode": None,
        "amount": None,
        "amount_is_full_balance": False,
        "card_number": None,
        "card_cvv": None,
        "card_expiry_month": None,
        "card_expiry_year": None,
        "cardholder_name": None,
        "wants_to_stop": False,
        "wants_info_repeated": False,
        "wants_to_switch_account": False,
    }
    base.update(overrides)
    return base


class FakeExtractor:
    """Returns pre-scripted extraction dicts, one per call, in order."""

    def __init__(self, responses):
        self._responses = list(responses)

    def extract(self, transcript, latest_user_message, stage_hint):
        if not self._responses:
            raise AssertionError(
                "FakeExtractor ran out of scripted responses -- the test "
                "script and the FSM's actual turn count have diverged."
            )
        return self._responses.pop(0)


class FakeAPIClient:
    """Stands in for PaymentAPIClient.

    - `accounts`: dict of account_id -> raw lookup-account JSON response.
    - `payment_error`: a PaymentAPIError to raise from every process_payment
      call (simulates a persistently failing card/network).
    - `payment_result`: the dict process_payment returns on success.
    """

    def __init__(self, accounts=None, payment_result=None, payment_error=None):
        self.accounts = accounts or {}
        self.payment_result = payment_result
        self.payment_error = payment_error
        self.payment_calls = []

    def lookup_account(self, account_id):
        if account_id not in self.accounts:
            raise PaymentAPIError("account_not_found", "No account found with the provided account_id.")
        return self.accounts[account_id]

    def process_payment(self, account_id, amount, card):
        self.payment_calls.append((account_id, amount, dict(card)))
        if self.payment_error is not None:
            raise self.payment_error
        return self.payment_result or {"transaction_id": "txn_test_1"}


ACC1001 = {
    "account_id": "ACC1001",
    "full_name": "Nithin Jain",
    "dob": "1990-05-14",
    "aadhaar_last4": "4321",
    "pincode": "400001",
    "balance": 1250.75,
}

ACC1002 = {
    "account_id": "ACC1002",
    "full_name": "Rajarajeswari Balasubramaniam",
    "dob": "1985-11-23",
    "aadhaar_last4": "9876",
    "pincode": "400002",
    "balance": 540.00,
}

ACC1003 = {
    "account_id": "ACC1003",
    "full_name": "Priya Agarwal",
    "dob": "1992-08-10",
    "aadhaar_last4": "2468",
    "pincode": "400003",
    "balance": 0.00,
}

ACC1004 = {
    "account_id": "ACC1004",
    "full_name": "Rahul Mehta",
    "dob": "1988-02-29",
    "aadhaar_last4": "1357",
    "pincode": "400004",
    "balance": 3200.50,
}

VALID_CARD_NUMBER = "4532015112830366"  # passes Luhn; from the assignment's own API example
