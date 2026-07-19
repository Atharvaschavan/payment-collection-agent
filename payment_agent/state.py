"""Conversation state: the single source of truth the FSM reads and writes.

Nothing in here is derived from LLM output directly -- fields are populated
by the orchestrator after it has decided (deterministically) that a value is
trustworthy enough to store.
"""
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import List, Optional


class Stage(str, Enum):
    AWAIT_ACCOUNT_ID = "await_account_id"
    AWAIT_IDENTITY = "await_identity"
    AWAIT_AMOUNT = "await_amount"
    AWAIT_CARD_DETAILS = "await_card_details"
    CLOSED_SUCCESS = "closed_success"
    CLOSED_FAILURE = "closed_failure"


@dataclass
class AccountRecord:
    """Sensitive account data fetched from the lookup API.

    This object (and its dob/aadhaar_last4/pincode fields in particular) is
    never serialized into any LLM prompt and never echoed back to the user --
    see DESIGN.md "Do not expose sensitive user data".
    """

    account_id: str
    full_name: str
    dob: str
    aadhaar_last4: str
    pincode: str
    balance: Decimal


@dataclass
class PendingCard:
    """Card fields collected so far, possibly across several turns."""

    card_number: Optional[str] = None
    cvv: Optional[str] = None
    expiry_month: Optional[int] = None
    expiry_year: Optional[int] = None
    cardholder_name: Optional[str] = None

    def is_complete(self) -> bool:
        return bool(self.card_number and self.cvv and self.expiry_month and self.expiry_year)

    def clear(self) -> None:
        self.card_number = None
        self.cvv = None
        self.expiry_month = None
        self.expiry_year = None
        self.cardholder_name = None


@dataclass
class ConversationState:
    stage: Stage = Stage.AWAIT_ACCOUNT_ID
    turn_count: int = 0

    # Account lookup
    account_id: Optional[str] = None
    account: Optional[AccountRecord] = None
    lookup_attempts: int = 0

    # Identity verification (claims are cleared after every failed attempt)
    claimed_name: Optional[str] = None
    claimed_dob: Optional[str] = None
    claimed_aadhaar_last4: Optional[str] = None
    claimed_pincode: Optional[str] = None
    invalid_date_notice: bool = False
    verified: bool = False
    verified_name: Optional[str] = None
    identity_attempts: int = 0

    # Payment amount
    pending_amount_raw: Optional[object] = None
    pending_amount_full_balance: bool = False
    amount: Optional[Decimal] = None

    # Card collection / payment
    pending_card: PendingCard = field(default_factory=PendingCard)
    payment_attempts: int = 0
    transaction_id: Optional[str] = None

    # Termination
    closed: bool = False
    close_reason: Optional[str] = None

    # Rolling transcript replayed to the LLM extractor for multi-turn context
    # (pronoun resolution, corrections like "actually my name is X"). Capped
    # in orchestrator._record_turn.
    transcript: List[dict] = field(default_factory=list)
