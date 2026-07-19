from decimal import Decimal

from payment_agent import verification
from payment_agent.state import AccountRecord

ACCOUNT = AccountRecord(
    account_id="ACC1001",
    full_name="Nithin Jain",
    dob="1990-05-14",
    aadhaar_last4="4321",
    pincode="400001",
    balance=Decimal("1250.75"),
)


def test_needs_both_when_nothing_supplied():
    assert verification.evaluate(ACCOUNT, None) == verification.Outcome.NEED_BOTH


def test_needs_name_when_only_secondary_supplied():
    assert verification.evaluate(ACCOUNT, None, claimed_dob="1990-05-14") == verification.Outcome.NEED_NAME


def test_needs_secondary_when_only_name_supplied():
    assert verification.evaluate(ACCOUNT, "Nithin Jain") == verification.Outcome.NEED_SECONDARY


def test_success_with_dob():
    outcome = verification.evaluate(ACCOUNT, "Nithin Jain", claimed_dob="1990-05-14")
    assert outcome == verification.Outcome.SUCCESS


def test_success_with_aadhaar():
    outcome = verification.evaluate(ACCOUNT, "Nithin Jain", claimed_aadhaar_last4="4321")
    assert outcome == verification.Outcome.SUCCESS


def test_success_with_pincode():
    outcome = verification.evaluate(ACCOUNT, "Nithin Jain", claimed_pincode="400001")
    assert outcome == verification.Outcome.SUCCESS


def test_fail_on_name_mismatch_even_with_correct_secondary():
    outcome = verification.evaluate(ACCOUNT, "Nithin Jainn", claimed_dob="1990-05-14")
    assert outcome == verification.Outcome.FAIL


def test_fail_no_case_insensitive_workaround():
    # Strict matching -- lowercase name must NOT pass even though it "looks"
    # like a match. This is a hard requirement, not an oversight.
    outcome = verification.evaluate(ACCOUNT, "nithin jain", claimed_dob="1990-05-14")
    assert outcome == verification.Outcome.FAIL


def test_fail_when_secondary_is_wrong():
    outcome = verification.evaluate(ACCOUNT, "Nithin Jain", claimed_dob="1991-01-01")
    assert outcome == verification.Outcome.FAIL


def test_fail_when_secondary_belongs_to_wrong_field():
    # Correct pincode value supplied as if it were the Aadhaar last 4 --
    # must not match by accident.
    outcome = verification.evaluate(ACCOUNT, "Nithin Jain", claimed_aadhaar_last4="400001")
    assert outcome == verification.Outcome.FAIL
