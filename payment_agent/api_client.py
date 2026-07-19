"""Thin HTTP client for the two provided payment-verification APIs.

Every failure mode -- HTTP error codes, the API's own error_code field, and
network/connection failures -- is normalized into a single PaymentAPIError so
the orchestrator has one place to reason about "what went wrong" regardless
of where in the stack it happened.
"""
from decimal import Decimal
from typing import Optional

import requests

from . import config


class PaymentAPIError(Exception):
    """A normalized API failure.

    error_code mirrors the API's documented vocabulary (account_not_found,
    invalid_amount, insufficient_balance, invalid_card, invalid_cvv,
    invalid_expiry) plus two synthetic codes this client introduces:
    "network_error" (couldn't reach the service at all) and "unknown_error"
    (a response we didn't recognize).
    """

    def __init__(self, error_code: str, message: str, http_status: Optional[int] = None):
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.http_status = http_status


class PaymentAPIClient:
    def __init__(self, base_url: str = config.API_BASE_URL, timeout: int = config.HTTP_TIMEOUT_SECONDS):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def lookup_account(self, account_id: str) -> dict:
        url = f"{self.base_url}{config.LOOKUP_ACCOUNT_PATH}"
        try:
            resp = requests.post(url, json={"account_id": account_id}, timeout=self.timeout)
        except requests.exceptions.RequestException as exc:
            raise PaymentAPIError(
                "network_error", f"Could not reach the account service: {exc}"
            ) from exc

        if resp.status_code == 200:
            return resp.json()

        body = self._safe_json(resp)
        raise PaymentAPIError(
            body.get("error_code", "unknown_error"),
            body.get("message", f"Account lookup failed with status {resp.status_code}"),
            resp.status_code,
        )

    def process_payment(self, account_id: str, amount: Decimal, card: dict) -> dict:
        url = f"{self.base_url}{config.PROCESS_PAYMENT_PATH}"
        payload = {
            "account_id": account_id,
            "amount": round(float(amount), 2),
            "payment_method": {
                "type": "card",
                "card": {
                    "cardholder_name": card["cardholder_name"],
                    "card_number": card["card_number"],
                    "cvv": card["cvv"],
                    "expiry_month": card["expiry_month"],
                    "expiry_year": card["expiry_year"],
                },
            },
        }
        try:
            resp = requests.post(url, json=payload, timeout=self.timeout)
        except requests.exceptions.RequestException as exc:
            raise PaymentAPIError(
                "network_error", f"Could not reach the payment service: {exc}"
            ) from exc

        body = self._safe_json(resp)
        if resp.status_code == 200 and body.get("success"):
            return {"transaction_id": body["transaction_id"]}

        raise PaymentAPIError(
            body.get("error_code", "unknown_error"),
            body.get("message", f"Payment failed with status {resp.status_code}"),
            resp.status_code,
        )

    @staticmethod
    def _safe_json(resp) -> dict:
        try:
            return resp.json()
        except ValueError:
            return {}
