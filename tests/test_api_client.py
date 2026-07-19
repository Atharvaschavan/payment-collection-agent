"""Unit tests for the HTTP client's error-code mapping.

These mock requests.post so every documented API error code (including
insufficient_balance, which the agent's own client-side validation normally
prevents from ever reaching the API -- see DESIGN.md "defense in depth") can
be exercised directly against the client, independent of the FSM.
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from payment_agent.api_client import PaymentAPIClient, PaymentAPIError


def _response(status_code, json_body):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body
    return resp


@pytest.fixture
def client():
    return PaymentAPIClient(base_url="https://example.invalid", timeout=5)


def test_lookup_account_success(client):
    with patch("payment_agent.api_client.requests.post") as mock_post:
        mock_post.return_value = _response(200, {
            "account_id": "ACC1001", "full_name": "Nithin Jain", "dob": "1990-05-14",
            "aadhaar_last4": "4321", "pincode": "400001", "balance": 1250.75,
        })
        result = client.lookup_account("ACC1001")
    assert result["full_name"] == "Nithin Jain"


def test_lookup_account_not_found(client):
    with patch("payment_agent.api_client.requests.post") as mock_post:
        mock_post.return_value = _response(404, {
            "error_code": "account_not_found",
            "message": "No account found with the provided account_id.",
        })
        with pytest.raises(PaymentAPIError) as exc_info:
            client.lookup_account("ACC9999")
    assert exc_info.value.error_code == "account_not_found"


def test_lookup_account_network_error(client):
    import requests

    with patch("payment_agent.api_client.requests.post", side_effect=requests.exceptions.ConnectionError("boom")):
        with pytest.raises(PaymentAPIError) as exc_info:
            client.lookup_account("ACC1001")
    assert exc_info.value.error_code == "network_error"


def test_process_payment_success(client):
    with patch("payment_agent.api_client.requests.post") as mock_post:
        mock_post.return_value = _response(200, {
            "success": True, "transaction_id": "txn_1762510325322_l1fl4oy",
        })
        result = client.process_payment("ACC1001", Decimal("500.00"), {
            "cardholder_name": "Nithin Jain", "card_number": "4532015112830366",
            "cvv": "123", "expiry_month": 12, "expiry_year": 2027,
        })
    assert result["transaction_id"] == "txn_1762510325322_l1fl4oy"


@pytest.mark.parametrize("error_code", [
    "invalid_amount", "insufficient_balance", "invalid_card", "invalid_cvv", "invalid_expiry",
])
def test_process_payment_documented_error_codes(client, error_code):
    with patch("payment_agent.api_client.requests.post") as mock_post:
        mock_post.return_value = _response(422, {"success": False, "error_code": error_code})
        with pytest.raises(PaymentAPIError) as exc_info:
            client.process_payment("ACC1001", Decimal("500.00"), {
                "cardholder_name": "Nithin Jain", "card_number": "4532015112830366",
                "cvv": "123", "expiry_month": 12, "expiry_year": 2027,
            })
    assert exc_info.value.error_code == error_code


def test_process_payment_invalid_args_error_code(client):
    # Not in the assignment's documented error-code table, but observed
    # live against the real sandbox API: a wrong-length CVV and an expired
    # card both return HTTP 400 (not 422) with error_code "invalid_args"
    # rather than the documented "invalid_cvv" / "invalid_expiry". The
    # client must still surface this correctly regardless of status code --
    # orchestrator.py's handling of it is regression-tested separately in
    # tests/test_fsm_scripted.py.
    with patch("payment_agent.api_client.requests.post") as mock_post:
        mock_post.return_value = _response(400, {"success": False, "error_code": "invalid_args"})
        with pytest.raises(PaymentAPIError) as exc_info:
            client.process_payment("ACC1001", Decimal("500.00"), {
                "cardholder_name": "Nithin Jain", "card_number": "4532015112830366",
                "cvv": "12", "expiry_month": 12, "expiry_year": 2027,
            })
    assert exc_info.value.error_code == "invalid_args"
    assert exc_info.value.http_status == 400


def test_process_payment_network_error(client):
    import requests

    with patch("payment_agent.api_client.requests.post", side_effect=requests.exceptions.Timeout("boom")):
        with pytest.raises(PaymentAPIError) as exc_info:
            client.process_payment("ACC1001", Decimal("500.00"), {
                "cardholder_name": "Nithin Jain", "card_number": "4532015112830366",
                "cvv": "123", "expiry_month": 12, "expiry_year": 2027,
            })
    assert exc_info.value.error_code == "network_error"
