"""Live evaluation harness -- runs the REAL agent (real LLM extraction, real
sandbox API) through scripted multi-turn scenarios built from the
assignment's own "what real users sound like" examples, and reports
pass/fail per scenario.

This is deliberately separate from tests/test_fsm_scripted.py, which is
fast, free, and fully deterministic by using fakes for both the LLM and the
API. This harness instead answers a different question: "given genuinely
messy, real free-form input, does the real LLM extraction actually work
end-to-end against the real system?" See EVALUATION.md for the full
rationale and how to read the output.

Usage:
    export OPENAI_API_KEY="..."   # or put it in a .env file, see .env.example
    python eval/eval_harness.py
"""
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, List

# Optional pacing between turns, purely for this test harness -- NOT
# something the production Agent does (a real conversation shouldn't have an
# artificial per-turn delay baked in). Defaults to 0: the openai SDK already
# retries rate limits/5xx with backoff by default, and a paid-tier key
# typically has enough headroom that no extra pacing is needed. Set
# EVAL_HARNESS_TURN_DELAY_SECONDS if you're on a constrained free-tier key.
SECONDS_BETWEEN_TURNS = float(os.environ.get("EVAL_HARNESS_TURN_DELAY_SECONDS", "0"))

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import Agent  # noqa: E402

# Transcripts are printed with a rupee sign (₹). Windows terminals often
# default to a legacy codepage (cp1252) that can't encode it, which would
# otherwise crash mid-scenario. Force UTF-8 stdout so this works the same on
# every platform.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


@dataclass
class Scenario:
    name: str
    turns: List[str]
    check: Callable[[Agent], None]  # raises AssertionError on failure
    notes: str = ""


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def scenario_happy_path_messy_input() -> Scenario:
    def check(agent: Agent) -> None:
        state = agent._impl.state
        _assert(state.closed, "expected the session to close")
        _assert(state.stage.value == "closed_success", f"expected success, got {state.stage}")
        _assert(state.transaction_id is not None, "expected a transaction id")
        _assert(str(state.amount) == "500.00", f"expected amount 500.00, got {state.amount}")

    return Scenario(
        name="Happy path with messy input (ACC1001)",
        turns=[
            "Hi",
            "yeah my account number is ACC1001 I think",
            "it's Nithin, Nithin Jain",
            "I was born on 14th May 1990",
            "can I do 500 for now?",
            "the card number is 4532 0151 1283 0366, expires December 2027, CVV is one two three",
        ],
        check=check,
        notes="Exercises: fuzzy account-id phrasing, 'it's X, X' name phrasing, "
        "worded date, partial-payment phrasing, spaced card number + worded "
        "expiry + spoken-digit CVV all in one message.",
    )


def scenario_verification_failure_exhausted() -> Scenario:
    def check(agent: Agent) -> None:
        state = agent._impl.state
        _assert(state.closed, "expected the session to close")
        _assert(state.close_reason == "verification_exhausted", f"got {state.close_reason}")
        _assert(state.identity_attempts == 3, f"expected 3 attempts, got {state.identity_attempts}")
        _assert(not state.verified, "must never be verified after exhausting retries")

    return Scenario(
        name="Verification failure exhausts retries (ACC1002)",
        turns=[
            "Hi",
            "account id: acc1002",
            "my name is Rajarajeswari Balasubramaniam, DOB 1990-01-01",
            "my name is Rajarajeswari Balasubramaniam, pincode 111111",
            "my name is Rajarajeswari Balasubramaniam, Aadhaar last four 0000",
        ],
        check=check,
        notes="Every secondary factor supplied is wrong; the correct name is "
        "reused across attempts on purpose to isolate that the SECONDARY "
        "factor, not the name, is what's failing.",
    )


def scenario_payment_failure_expired_card_then_success() -> Scenario:
    def check(agent: Agent) -> None:
        state = agent._impl.state
        _assert(state.closed, "expected the session to eventually close")
        _assert(state.stage.value == "closed_success", f"expected eventual success, got {state.stage}")
        _assert(state.transaction_id is not None, "expected a transaction id")

    return Scenario(
        name="Payment failure: expired card, then corrected (ACC1004)",
        turns=[
            "Hi",
            "ACC1004",
            "Rahul Mehta",
            "DOB is 1988-02-29",
            "pay 1000",
            "card 4111111111111111, cvv 123, expiry 01/2020",
            "sorry, the expiry is actually 01/2030",
        ],
        check=check,
        notes="1988-02-29 is a genuine leap-year DOB (must verify). "
        "01/2020 is an already-expired card -- the agent should reject it "
        "and ask again; supplying only the corrected expiry (keeping the "
        "same card number/CVV) should then succeed.",
    )


def scenario_edge_case_rhetorical_aside_and_full_balance() -> Scenario:
    def check(agent: Agent) -> None:
        state = agent._impl.state
        _assert(state.verified, "expected identity to verify from the Aadhaar value alone")
        _assert(state.closed, "expected the session to close")
        _assert(state.stage.value == "closed_success", f"expected success, got {state.stage}")
        _assert(state.transaction_id is not None, "expected a transaction id")

    return Scenario(
        name="Edge case: rhetorical aside embedded in the answer + 'full amount' phrasing (ACC1002)",
        turns=[
            "Hi",
            "acc 1002",
            "Rajarajeswari Balasubramaniam",
            "Aadhaar ends with 9876, shall I give pincode instead?",
            "just clear the full amount",
            "card number 4532015112830366, expiry 12/27, cvv 123",
        ],
        check=check,
        notes="This is the assignment's own example verbatim: the LLM must "
        "extract aadhaar_last4='9876' despite the trailing rhetorical "
        "question, and 'full amount' must resolve to the exact balance "
        "(540.00), not a guessed number.",
    )


SCENARIOS = [
    scenario_happy_path_messy_input,
    scenario_verification_failure_exhausted,
    scenario_payment_failure_expired_card_then_success,
    scenario_edge_case_rhetorical_aside_and_full_balance,
]


def run() -> int:
    if not os.environ.get("OPENAI_API_KEY"):
        print(
            "OPENAI_API_KEY is not set. This harness calls the real "
            "OpenAI API and the real sandbox payment API -- set the key "
            "(or add it to a .env file, see .env.example) and re-run. "
            "See README.md."
        )
        return 1

    results = []
    for scenario_index, build in enumerate(SCENARIOS):
        if scenario_index > 0:
            time.sleep(SECONDS_BETWEEN_TURNS)
        scenario = build()
        print(f"\n=== {scenario.name} ===")
        if scenario.notes:
            print(f"    ({scenario.notes})")
        agent = Agent()
        transcript_ok = True
        try:
            for i, turn in enumerate(scenario.turns):
                if i > 0:
                    time.sleep(SECONDS_BETWEEN_TURNS)
                result = agent.next(turn)
                print(f"  You:   {turn}")
                print(f"  Agent: {result['message']}")
            scenario.check(agent)
        except AssertionError as exc:
            transcript_ok = False
            print(f"  FAIL: {exc}")
        except Exception as exc:  # noqa: BLE001
            transcript_ok = False
            print(f"  ERROR: {exc!r}")

        status = "PASS" if transcript_ok else "FAIL"
        print(f"  --> {status}")
        results.append((scenario.name, transcript_ok))

    print("\n=== Summary ===")
    passed = sum(1 for _, ok in results if ok)
    for name, ok in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    print(f"\n{passed}/{len(results)} scenarios passed.")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(run())
