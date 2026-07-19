"""Deterministic, non-fuzzy validation helpers.

Per the assignment's hard rules, every input must be validated in code
*before* any API call, and identity matching must be strict (no fuzzy or
case-insensitive workarounds). This module -- together with verification.py
-- is where that strictness lives. None of it depends on the LLM.
"""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional, Tuple


class ValidationError(ValueError):
    """Raised with a user-facing explanation of why a value was rejected."""


ACCOUNT_ID_RE = re.compile(r"^ACC\d+$")


def normalize_account_id(raw: Optional[str]) -> Optional[str]:
    """Uppercases and strips whitespace/punctuation from an extracted
    account ID (e.g. "acc 1001" -> "ACC1001").

    The LLM is separately instructed to normalize this itself, but live
    testing found that instruction is not reliable enough to depend on
    alone: gpt-4.1-mini consistently (not a one-off) returned "acc 1001"
    unnormalized despite an explicit example in its own system prompt.
    Doing it here deterministically means correctness for
    this field never depends on a model getting a string-formatting
    instruction right on any given call.
    """
    if raw is None:
        return None
    return re.sub(r"[^A-Za-z0-9]", "", raw).upper()


def is_valid_account_id(value: Optional[str]) -> bool:
    return bool(value) and bool(ACCOUNT_ID_RE.match(value))


def normalize_amount(raw) -> Decimal:
    """Validate and normalize a payment amount.

    Mirrors the API's own rule ("Amount is zero, negative, or has more than 2
    decimal places" -> invalid_amount) so bad amounts are caught before an API
    round-trip.
    """
    try:
        amount = Decimal(str(raw))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError("I couldn't understand that amount.")
    if amount <= 0:
        raise ValidationError("The amount must be greater than zero.")
    quantized = amount.quantize(Decimal("0.01"))
    if quantized != amount:
        raise ValidationError("Amounts can have at most 2 decimal places.")
    return quantized


def parse_iso_date(value: Optional[str]) -> Optional[date]:
    """Parse a YYYY-MM-DD string into a real calendar date, or None.

    Uses datetime.strptime so that impossible dates (e.g. 1990-02-29, since
    1990 is not a leap year) are rejected, while genuinely valid leap-year
    dates (e.g. 1988-02-29, since 1988 is a leap year) are accepted.
    """
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def luhn_check(number: str) -> bool:
    digits = [int(d) for d in number]
    checksum = 0
    parity = len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def is_amex(card_number: str) -> bool:
    return bool(card_number) and card_number.startswith(("34", "37"))


def validate_card_number(number: Optional[str]) -> Tuple[bool, Optional[str]]:
    """Returns (ok, error_code). error_code mirrors the API's own vocabulary
    ("invalid_card") so the same message-mapping table works for both
    client-side and API-side rejections.
    """
    if not number or not number.isdigit():
        return False, "invalid_card"
    if not (13 <= len(number) <= 19):
        return False, "invalid_card"
    if not luhn_check(number):
        return False, "invalid_card"
    return True, None


def validate_cvv(cvv: Optional[str], card_number: Optional[str]) -> Tuple[bool, Optional[str]]:
    if not cvv or not cvv.isdigit():
        return False, "invalid_cvv"
    expected_len = 4 if is_amex(card_number or "") else 3
    if len(cvv) != expected_len:
        return False, "invalid_cvv"
    return True, None


def validate_expiry(month, year, today: Optional[date] = None) -> Tuple[bool, Optional[str]]:
    today = today or date.today()
    try:
        month = int(month)
        year = int(year)
    except (TypeError, ValueError):
        return False, "invalid_expiry"
    if year < 100:
        year += 2000
    if not (1 <= month <= 12):
        return False, "invalid_expiry"
    if (year, month) < (today.year, today.month):
        return False, "invalid_expiry"
    return True, None
