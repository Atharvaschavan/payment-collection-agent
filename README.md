# Payment Collection Agent

A conversational AI agent that greets a user, looks up their account, verifies
their identity, shares their balance, collects a card payment, and reports the
outcome — built for the "Build a Production-Ready Payment Collection AI
Agent" take-home assignment.

See **[DESIGN.md](DESIGN.md)** for the full architecture writeup and the
reasoning behind every design decision (LLM-driven extraction vs.
deterministic verification, retry limits, the leap-year edge case, etc.).
See **[SAMPLE_CONVERSATIONS.md](SAMPLE_CONVERSATIONS.md)** for real
transcripts (successful flow, verification failure, payment failure, and an
edge case). See **[eval/EVALUATION.md](eval/EVALUATION.md)** for the
evaluation approach, metrics, and an automated harness, and
**[eval/phase_tests/](eval/phase_tests/)** for a phase-by-phase live
verification of all 8 steps in the assignment's problem statement (62/62
passing — see `PHASE_1_RESULTS.md` through `PHASE_8_RESULTS.md`), plus
`COMBINED_PHASE_RESULTS.md` (context retention across a continuous
conversation and across the LLM's transcript window) and
`untested_risks_test.json` (ambiguous phrasing and prompt-injection
robustness) — 71/71 live test cases in total.

## Setup

Requires Python 3.10+. Using a virtual environment is recommended so this
project's dependencies don't collide with anything else on your machine:

```bash
python -m venv .venv

# macOS/Linux
source .venv/bin/activate
# Windows (PowerShell / Git Bash)
.venv\Scripts\activate      # or ./.venv/Scripts/python.exe directly

pip install -r requirements.txt
```

Set your OpenAI API key (the agent calls OpenAI to understand free-form user
input — see DESIGN.md §4.1 for why). Easiest: copy `.env.example` to `.env`
and fill it in -- it's loaded automatically at startup and already
git-ignored:

```bash
cp .env.example .env
# then edit .env and set OPENAI_API_KEY=...
```

Or export it directly instead:

```bash
# macOS/Linux
export OPENAI_API_KEY="..."

# Windows PowerShell
$env:OPENAI_API_KEY = "..."
```

Get a key at [platform.openai.com/api-keys](https://platform.openai.com/api-keys).

The payment/lookup API base URL is pre-configured to the sandbox provided in
the assignment and needs no setup. It can be overridden with
`PAYMENT_API_BASE_URL` if needed.

## Running it

**Interactively, from the terminal:**

```bash
python cli.py
```

**Programmatically, via the required interface:**

```python
from agent import Agent

agent = Agent()
print(agent.next("Hi"))
print(agent.next("My account ID is ACC1001"))
```

Every call to `agent.next(user_input)` returns `{"message": str}` and the
`Agent` instance holds all conversation state internally, exactly per the
assignment's required interface (`agent.py`) — no external setup or manual
resets are needed between turns.

## Test accounts (sandbox)

| Account ID | Full Name | DOB | Aadhaar Last 4 | Pincode | Balance |
|---|---|---|---|---|---|
| ACC1001 | Nithin Jain | 1990-05-14 | 4321 | 400001 | ₹1,250.75 |
| ACC1002 | Rajarajeswari Balasubramaniam | 1985-11-23 | 9876 | 400002 | ₹540.00 |
| ACC1003 | Priya Agarwal | 1992-08-10 | 2468 | 400003 | ₹0.00 (closes with no payment collected — see DESIGN.md §4.6) |
| ACC1004 | Rahul Mehta | 1988-02-29 (leap year) | 1357 | 400004 | ₹3,200.50 |

## Running the tests

```bash
pytest tests/ -v
```

These 68 tests are fully offline and free — they use fakes for both the LLM
and the payment API (`tests/fakes.py`), so they run the exact same way every
time and don't require `OPENAI_API_KEY`. They cover:

- Validators (Luhn, CVV-by-network, expiry, amount, account-ID format,
  leap-year date parsing) — `tests/test_validators.py`
- Strict identity verification, including the "no case-insensitive
  workaround" requirement — `tests/test_verification.py`
- Every documented `process-payment` / `lookup-account` API error code,
  mocked at the HTTP layer — `tests/test_api_client.py`
- `LLMExtractor`'s request construction and response parsing (forced tool
  call, system message + transcript ordering), mocked at the `openai.OpenAI`
  client boundary — `tests/test_extraction.py`
- The full conversation state machine end-to-end: successful flow,
  out-of-order input, "full amount" phrasing, the exact-balance boundary
  case, a zero-balance account (ACC1003) closing with no payment collected,
  a zero amount explicitly rejected, a cardholder name differing from the
  verified identity, verification-retry exhaustion, payment-retry exhaustion
  (both API-level and local-validation-level), insufficient balance,
  account-lookup exhaustion, cancellation, LLM-outage graceful degradation,
  and the ACC1004 leap-year edge case in all three of its forms (exact
  match, valid-but-wrong nearby date, and a genuinely impossible date) —
  `tests/test_fsm_scripted.py`

## Running the live phase-by-phase tests

The primary live verification is a set of JSON test files, one per step of
the assignment's 8-step problem statement, run against the real `Agent`
class with real OpenAI extraction and the real sandbox API:

```bash
export OPENAI_API_KEY="..."   # or set it in .env
python eval/run_phase_test.py eval/phase_tests/phase_1_greeting.json
# or run every phase in one go:
python eval/run_phase_test.py eval/phase_tests/phase_*.json
```

See `eval/phase_tests/PHASE_1_RESULTS.md` through `PHASE_8_RESULTS.md` for
what each phase checks, every real bug this process found and how it was
fixed (most notably a live API-contract mismatch on card errors — see
Phase 6), and the full pass tally (71/71 live test cases as of the last run).

## Running the live evaluation harness

The scripted tests above intentionally never call the real LLM (see
DESIGN.md §4.1/§8 and EVALUATION.md for why extraction quality is evaluated
separately). As a second, independent live check (4 broader end-to-end
scenarios rather than a per-step breakdown), you can also run:

```bash
export OPENAI_API_KEY="..."   # or set it in .env
python eval/eval_harness.py
```

This prints a pass/fail report per scenario. See `eval/EVALUATION.md` for
what "correct" means for each step and what to expect.

> **Rate-limit note:** the harness makes ~24 LLM calls across its 4
> scenarios. The `openai` SDK already retries rate limits/5xx with backoff
> by default, and a paid-tier key normally has enough headroom that this
> just works. If you're on a very constrained free-tier key and hit
> persistent 429s, set `EVAL_HARNESS_TURN_DELAY_SECONDS` (e.g. to `5`) to
> pace the harness's own calls.

## Project layout

```
agent.py                    # Required top-level Agent interface (thin adapter)
cli.py                      # Interactive terminal REPL
payment_agent/
  config.py                 # Tunable constants (retry limits, model, base URL)
  state.py                  # ConversationState / Stage / AccountRecord / PendingCard
  validators.py              # Deterministic format/Luhn/date/amount validation
  verification.py            # Strict identity verification (no LLM, no fuzzy matching)
  api_client.py              # HTTP client for lookup-account / process-payment
  extraction.py              # The one LLM call: forced-function-call NLU extraction (OpenAI)
  nlg.py                     # Templated (non-LLM) response text
  orchestrator.py            # The conversation state machine
tests/                       # Offline, deterministic unit + FSM tests (pytest)
eval/
  eval_harness.py            # Live scenario runner (real LLM + real sandbox API)
  run_phase_test.py          # Generic runner for the phase_tests/ JSON files
  phase_tests/                # One JSON test file + PHASE_N_RESULTS.md per assignment step (1-8)
  EVALUATION.md              # Evaluation approach, metrics, and observations
DESIGN.md                    # Architecture and design rationale
SAMPLE_CONVERSATIONS.md      # Real transcripts: success / verification failure /
                              # payment failure / edge case
```
