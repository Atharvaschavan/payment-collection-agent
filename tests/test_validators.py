from decimal import Decimal

import pytest

from payment_agent import validators
from tests.fakes import VALID_CARD_NUMBER


def test_valid_account_id():
    assert validators.is_valid_account_id("ACC1001")
    assert not validators.is_valid_account_id("acc1001")
    assert not validators.is_valid_account_id("1001")
    assert not validators.is_valid_account_id(None)


def test_normalize_account_id_handles_messy_llm_output():
    # gpt-4.1-mini was found, live and reproducibly, to sometimes leave
    # this un-normalized despite its own prompt instructions. This
    # deterministic normalization is the actual fix.
    assert validators.normalize_account_id("acc 1001") == "ACC1001"
    assert validators.normalize_account_id("ACC 1001") == "ACC1001"
    assert validators.normalize_account_id("acc-1001") == "ACC1001"
    assert validators.normalize_account_id("ACC1001") == "ACC1001"
    assert validators.normalize_account_id(None) is None


def test_normalize_amount_accepts_whole_and_two_decimal_values():
    assert validators.normalize_amount(1000) == Decimal("1000.00")
    assert validators.normalize_amount("500.5") == Decimal("500.50")
    assert validators.normalize_amount(1250.75) == Decimal("1250.75")


def test_normalize_amount_rejects_zero_and_negative():
    with pytest.raises(validators.ValidationError):
        validators.normalize_amount(0)
    with pytest.raises(validators.ValidationError):
        validators.normalize_amount(-50)


def test_normalize_amount_rejects_more_than_two_decimals():
    with pytest.raises(validators.ValidationError):
        validators.normalize_amount(10.999)


def test_parse_iso_date_valid():
    assert validators.parse_iso_date("1990-05-14") is not None


def test_parse_iso_date_leap_year_edge_case():
    # 1988 IS a leap year -> Feb 29 is a real date.
    assert validators.parse_iso_date("1988-02-29") is not None
    # 1990 is NOT a leap year -> Feb 29 is not a real date.
    assert validators.parse_iso_date("1990-02-29") is None


def test_parse_iso_date_garbage():
    assert validators.parse_iso_date("not a date") is None
    assert validators.parse_iso_date("") is None
    assert validators.parse_iso_date(None) is None


def test_luhn_check_on_assignment_example_card():
    assert validators.luhn_check(VALID_CARD_NUMBER) is True


def test_validate_card_number():
    assert validators.validate_card_number(VALID_CARD_NUMBER) == (True, None)
    assert validators.validate_card_number("1234567890123456") == (False, "invalid_card")  # fails luhn
    assert validators.validate_card_number("123") == (False, "invalid_card")  # too short
    assert validators.validate_card_number("4532 0151 1283 0366") == (False, "invalid_card")  # not stripped/masked
    assert validators.validate_card_number(None) == (False, "invalid_card")


def test_validate_cvv_standard_and_amex():
    assert validators.validate_cvv("123", VALID_CARD_NUMBER) == (True, None)
    assert validators.validate_cvv("12", VALID_CARD_NUMBER) == (False, "invalid_cvv")
    # Amex (34/37 prefix) requires 4-digit CVV.
    assert validators.validate_cvv("1234", "371234567890123") == (True, None)
    assert validators.validate_cvv("123", "371234567890123") == (False, "invalid_cvv")


def test_validate_expiry():
    from datetime import date

    today = date(2026, 7, 19)
    assert validators.validate_expiry(12, 2027, today=today) == (True, None)
    assert validators.validate_expiry(12, 27, today=today) == (True, None)  # 2-digit year
    assert validators.validate_expiry(1, 2020, today=today) == (False, "invalid_expiry")  # expired
    assert validators.validate_expiry(13, 2027, today=today) == (False, "invalid_expiry")  # bad month
