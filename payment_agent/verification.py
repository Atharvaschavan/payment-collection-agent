"""Strict, deterministic identity verification.

Per the assignment's Verification Requirements: a user is verified only if
their full name matches EXACTLY (no fuzzy matching, no case-insensitive
workaround) AND at least one of {date of birth, Aadhaar last 4, pincode}
also matches exactly.

This is intentionally pure Python with no LLM involvement whatsoever: the
comparison an attacker (or a confused user) cannot argue their way around,
because it never passes through anything that "interprets" text.
"""
from enum import Enum, auto

from .state import AccountRecord


class Outcome(Enum):
    NEED_BOTH = auto()       # neither a name nor a secondary factor supplied yet
    NEED_NAME = auto()       # secondary factor given, but no name yet
    NEED_SECONDARY = auto()  # name given, but no secondary factor yet
    SUCCESS = auto()
    FAIL = auto()            # both supplied, but at least the name didn't match


def evaluate(
    account: AccountRecord,
    claimed_name,
    claimed_dob=None,
    claimed_aadhaar_last4=None,
    claimed_pincode=None,
) -> Outcome:
    has_name = bool(claimed_name)
    has_secondary = bool(claimed_dob or claimed_aadhaar_last4 or claimed_pincode)

    if not has_name and not has_secondary:
        return Outcome.NEED_BOTH
    if not has_name:
        return Outcome.NEED_NAME
    if not has_secondary:
        return Outcome.NEED_SECONDARY

    name_ok = claimed_name == account.full_name
    secondary_ok = (
        (claimed_dob is not None and claimed_dob == account.dob)
        or (claimed_aadhaar_last4 is not None and claimed_aadhaar_last4 == account.aadhaar_last4)
        or (claimed_pincode is not None and claimed_pincode == account.pincode)
    )
    return Outcome.SUCCESS if (name_ok and secondary_ok) else Outcome.FAIL
