"""The agent's natural-language-understanding layer, backed by OpenAI.

This is the ONLY place an LLM is called in the whole system, and it is given
exactly one job: turn the user's free-form latest message into structured
slots via a forced tool call (Chat Completions' `tool_choice` forced to a
single named function, with `strict: true` on the schema, guarantees both
that a call happens and that its arguments validate against the schema
exactly). It never sees account data, never decides whether identity is
verified, and never phrases anything the user reads -- see DESIGN.md for why
that split is deliberate.
"""
import json
from typing import List, Optional

import openai

from . import config

EXTRACTION_FUNCTION_NAME = "extract_conversation_data"

EXTRACTION_PARAMETERS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "intent": {
            "type": "string",
            "enum": [
                "provide_info",
                "greeting",
                "question",
                "chitchat",
                "wants_to_cancel",
                "other",
            ],
            "description": "Best single-label classification of the latest message.",
        },
        "account_id": {
            "type": ["string", "null"],
            "description": "Normalized to format ACCxxxx: uppercase, no spaces/punctuation.",
        },
        "full_name": {
            "type": ["string", "null"],
            "description": "The user's own full name exactly as stated (preserve original spelling/capitalization), only when they are stating their own identity.",
        },
        "date_of_birth": {
            "type": ["string", "null"],
            "description": "ISO format YYYY-MM-DD, e.g. '14th May 1990' -> '1990-05-14'.",
        },
        "aadhaar_last4": {
            "type": ["string", "null"],
            "description": "Last 4 digits of Aadhaar, digits only.",
        },
        "pincode": {
            "type": ["string", "null"],
            "description": "Postal pincode, digits only.",
        },
        "amount": {
            "type": ["number", "null"],
            "description": "A specific payment amount in rupees as a plain number, e.g. 'a thousand rupees' -> 1000. Do not set this for phrases like 'the full amount' -- use amount_is_full_balance instead.",
        },
        "amount_is_full_balance": {
            "type": "boolean",
            "description": "True if the user wants to pay their entire outstanding balance (e.g. 'full amount', 'clear everything', 'pay it all off').",
        },
        "card_number": {
            "type": ["string", "null"],
            "description": "Card number, digits only (spaces/dashes stripped).",
        },
        "card_cvv": {
            "type": ["string", "null"],
            "description": "Card CVV/CVC, digits only (spoken digits like 'one two three' -> '123').",
        },
        "card_expiry_month": {
            "type": ["integer", "null"],
            "description": "Card expiry month as an integer 1-12.",
        },
        "card_expiry_year": {
            "type": ["integer", "null"],
            "description": "Card expiry year as a 4-digit year (2-digit years like '27' -> 2027).",
        },
        "cardholder_name": {
            "type": ["string", "null"],
            "description": "Name printed on the card, ONLY if the user explicitly says the card is under a different name than their own.",
        },
        "wants_to_stop": {
            "type": "boolean",
            "description": "True if the user wants to cancel, quit, or end the conversation.",
        },
        "wants_to_switch_account": {
            "type": "boolean",
            "description": "True ONLY if the user explicitly wants to restart with a DIFFERENT account than the one already in use in this conversation -- e.g. 'actually, let's use a different account', 'wrong account, let me give you another one', 'can we start over with ACC1002 instead'. False for simply repeating or confirming the SAME account ID already in use. False if no account has been looked up yet in this conversation (there is nothing to switch away from).",
        },
        "wants_info_repeated": {
            "type": "boolean",
            "description": "True ONLY if the user is asking the agent to read back a piece of SENSITIVE IDENTIFYING information they (the user) already provided -- specifically their account ID, full name, date of birth, Aadhaar, pincode, or card details (number/CVV/expiry). E.g. 'what's my account ID again?', 'can you repeat that back to me?', 'what did I just give you?'. False if the information was never given yet (e.g. 'I'm not sure what my account ID is' -- there is nothing to repeat). False for general questions about the process. IMPORTANT: always False for questions about the account's OUTSTANDING BALANCE or amount owed (e.g. 'how much do I owe again?', 'remind me of my balance', 'what's my balance?') -- the balance is meant to be freely shared with a verified user, it is not sensitive identifying data, and asking about it again is a normal, legitimate question, not a security concern.",
        },
    },
    "required": [
        "intent",
        "account_id",
        "full_name",
        "date_of_birth",
        "aadhaar_last4",
        "pincode",
        "amount",
        "amount_is_full_balance",
        "card_number",
        "card_cvv",
        "card_expiry_month",
        "card_expiry_year",
        "cardholder_name",
        "wants_to_stop",
        "wants_info_repeated",
        "wants_to_switch_account",
    ],
}

EXTRACTION_TOOL = {
    "type": "function",
    "function": {
        "name": EXTRACTION_FUNCTION_NAME,
        "description": (
            "Extract structured information the user explicitly stated in "
            "their MOST RECENT message of a payment-collection conversation. "
            "Only fill a field if the user explicitly stated it in that "
            "latest message -- never guess, infer, or repeat values from "
            "earlier turns; the calling application already remembers those "
            "on its own. Normalize formats exactly as described per field."
        ),
        "strict": True,
        "parameters": EXTRACTION_PARAMETERS_SCHEMA,
    },
}

SYSTEM_PROMPT = """You are the natural-language-understanding component of a payment \
collection agent. You never talk to the user and you never make decisions -- \
you only extract structured fields from their latest message by calling the \
extract_conversation_data function exactly once per turn.

Field-specific normalization rules:
- account_id: uppercase, no spaces or punctuation (e.g. "acc 1001" -> "ACC1001").
- date_of_birth: ISO format YYYY-MM-DD (e.g. "14th May 1990" -> "1990-05-14"; \
"DOB is May 14, 90" -> "1990-05-14"). If the stated date is not a real \
calendar date (e.g. a nonexistent Feb 30), still normalize it as best you can \
-- the application will validate it separately.
- aadhaar_last4 / pincode: digits only, spaces removed.
- amount: a plain number of rupees (e.g. "a thousand rupees" -> 1000).
- card_number: digits only, spaces/dashes removed.
- card_cvv: digits only (spoken digits like "one two three" -> "123").
- card_expiry_year: a 4-digit year (2-digit years like "27" -> 2027).

Disambiguation for wants_to_stop vs. wants_info_repeated: a hesitation \
opener like "wait,", "hold on," or "actually," does NOT by itself mean the \
user wants to cancel -- only set wants_to_stop=true if they clearly want to \
end or abandon the conversation (e.g. "cancel this", "never mind, forget \
it", "I don't want to continue"). A request to repeat, confirm, or read \
back information (e.g. "wait, can you repeat my account ID?", "hold on, \
what did I just give you?") is wants_info_repeated=true and wants_to_stop \
must stay false -- these are two independent, mutually compatible flags; \
being unsure or asking for a pause is not the same as wanting to stop.

wants_info_repeated requires that the information was already given \
earlier in the conversation -- it means "read back what I already told \
you", not "I don't know this information". "I'm not sure what my account \
ID is" or "I don't know my account number" must have wants_info_repeated=\
false: nothing has been provided yet, so there is nothing to repeat; the \
user is expressing uncertainty about their own information, not requesting \
a readback.

wants_info_repeated also does NOT apply to the account's outstanding \
balance or amount owed -- that is not sensitive identifying data and the \
user is always entitled to ask about it again. "How much do I owe again?", \
"remind me of my balance", "what's my balance?" must all have \
wants_info_repeated=false; treat these as an ordinary question, not a \
repeat-of-sensitive-info request.

wants_to_switch_account is for the user explicitly wanting to abandon the \
account already in use and restart with a different one (e.g. "actually, \
wrong account, it's ACC1002 instead", "can we start over with a different \
account?"). Do not set this just because a long digit string appears \
somewhere in the message (e.g. a card number) -- it requires a clear, \
explicit statement that the account itself should change.

Never fabricate a value the user did not state in their latest message. If a \
field was not mentioned there, its value must be null (false for booleans), \
even if it was mentioned earlier in the conversation -- the calling \
application already remembers earlier values on its own and merges them in."""


class LLMExtractor:
    def __init__(self, client: Optional["openai.OpenAI"] = None, model: str = config.LLM_MODEL):
        # The OpenAI SDK already retries connection errors, 429, and 5xx
        # with exponential backoff by default (max_retries=2) -- no custom
        # retry wrapper needed here, unlike the Gemini backend this replaced.
        self.client = client or openai.OpenAI()
        self.model = model

    def extract(self, transcript: List[dict], latest_user_message: str, stage_hint: str) -> dict:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for turn in transcript:
            messages.append({"role": turn["role"], "content": turn["content"]})
        messages.append(
            {
                "role": "user",
                "content": f"[Current conversation stage: {stage_hint}]\n\n{latest_user_message}",
            }
        )

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=[EXTRACTION_TOOL],
            tool_choice={"type": "function", "function": {"name": EXTRACTION_FUNCTION_NAME}},
        )
        message = response.choices[0].message
        for tool_call in message.tool_calls or []:
            if tool_call.function.name == EXTRACTION_FUNCTION_NAME:
                return json.loads(tool_call.function.arguments)
        # Unreachable in practice: forced tool_choice guarantees exactly this call.
        return _blank_extraction()


def _blank_extraction() -> dict:
    return {
        "intent": "other",
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
