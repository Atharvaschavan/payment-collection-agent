"""Configuration constants for the payment collection agent.

Everything here is overridable via environment variables so the same code
runs unchanged in development, evaluation, and (hypothetically) production.
"""
import os

from dotenv import load_dotenv

# Loads a local .env file (if present) into the process environment -- this
# is how OPENAI_API_KEY gets picked up without exporting it in every shell.
# See .env.example. A missing .env file is not an error; load_dotenv() is a
# no-op in that case.
load_dotenv()

API_BASE_URL = os.environ.get(
    "PAYMENT_API_BASE_URL",
    "https://se-payment-verification-api.service.external.usea2.aws.prodigaltech.com",
)
LOOKUP_ACCOUNT_PATH = "/api/lookup-account"
PROCESS_PAYMENT_PATH = "/api/process-payment"

# The LLM is used *only* as the natural-language-understanding component that
# extracts structured slots from free-form user text. All numeric facts,
# identity comparisons, and payment decisions are computed afterwards in
# plain, deterministic Python -- see DESIGN.md ("Key decisions") for why.
# Requires OPENAI_API_KEY in the environment -- see .env.example -- which
# the openai client picks up automatically.
#
# gpt-4.1-mini, not the cheaper gpt-4.1-nano: repeated live testing on
# gpt-4.1-nano surfaced real, reproducible extraction misses (a correct DOB
# once misclassified as a mismatch, an amount once returned null) that cost
# the user a real retry attempt for the model's mistake, not theirs --
# see EVALUATION.md's Observations section. gpt-4.1-mini trades a small amount
# of cost/latency for meaningfully better consistency on a task where a
# wrong extraction has a real cost (a burned attempt against a hard retry
# limit), not just a wasted turn.
LLM_MODEL = os.environ.get("PAYMENT_AGENT_MODEL", "gpt-4.1-mini")

# Retry limits (Hard Rules require "a sensible retry limit" -- these are the
# agent's answer to what "sensible" means, tunable without a code change).
MAX_ACCOUNT_LOOKUP_ATTEMPTS = int(os.environ.get("PAYMENT_AGENT_MAX_LOOKUP_ATTEMPTS", "3"))
MAX_VERIFICATION_ATTEMPTS = int(os.environ.get("PAYMENT_AGENT_MAX_VERIFICATION_ATTEMPTS", "3"))
MAX_PAYMENT_ATTEMPTS = int(os.environ.get("PAYMENT_AGENT_MAX_PAYMENT_ATTEMPTS", "3"))

HTTP_TIMEOUT_SECONDS = int(os.environ.get("PAYMENT_AGENT_HTTP_TIMEOUT", "15"))

# How many past turns (user + assistant messages) are replayed to the LLM as
# context for extraction. Bounds cost/latency on very long conversations.
MAX_HISTORY_MESSAGES_FOR_EXTRACTION = int(
    os.environ.get("PAYMENT_AGENT_MAX_HISTORY_MESSAGES", "16")
)
