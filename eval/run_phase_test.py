"""Generic runner for phase-wise JSON test files.

Runs the REAL agent (real LLM extraction, real sandbox API) through the
scripted turns in one or more JSON test files under eval/phase_tests/, and
reports pass/fail per test case. This is a complementary, more granular
sibling to eval/eval_harness.py: eval_harness.py checks a handful of full
end-to-end scenarios, while this lets you build up and check one flow phase
at a time (phase 1: greeting, phase 2: account lookup, phase 3:
verification, ...), independent of whether later phases are built or
scripted yet.

JSON test file schema (see eval/phase_tests/phase_1_greeting.json for a
worked example):

    {
      "phase": 1,
      "phase_name": "...",
      "description": "...",
      "test_cases": [
        {
          "id": "unique_id",
          "description": "...",
          "turns": [
            {
              "user_input": "...",
              "expect": {
                "message_contains_all": ["..."],   // all must appear (case-insensitive)
                "message_contains_any": ["..."],   // at least one must appear
                "message_not_contains": ["..."],   // none may appear
                "state": {"stage": "...", "account_id": "...", "closed": false, ...}
              }
            }
          ]
        }
      ]
    }

Only the "expect" keys you actually include are checked; everything is
optional per turn. "state" keys are matched against ConversationState
attributes by name (Stage enums compare by their .value string, Decimals by
their str()). A dotted path reaches one level of nesting, e.g.
"account.full_name" or "account.balance" (state.account is an AccountRecord,
populated once account lookup succeeds; None before that, and any dotted
path under it resolves to None rather than raising).

Usage:
    export OPENAI_API_KEY="..."   # or set it in .env
    python eval/run_phase_test.py eval/phase_tests/phase_1_greeting.json
    python eval/run_phase_test.py eval/phase_tests/*.json
"""
import glob
import json
import os
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import Agent  # noqa: E402
from payment_agent.state import Stage  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


@dataclass
class TurnFailure:
    turn_index: int
    user_input: str
    reason: str
    actual_message: str


@dataclass
class TestCaseResult:
    test_id: str
    passed: bool
    failures: List[TurnFailure] = field(default_factory=list)


def _resolve_state_value(state, field_path: str) -> Any:
    """Resolves a possibly-dotted field path against ConversationState, e.g.
    "stage" or "account.full_name" (AccountRecord is nested one level under
    state.account). Returns None if an intermediate object is None (e.g.
    "account.full_name" before any lookup has succeeded) rather than raising,
    since a test may legitimately expect that.
    """
    value = state
    for part in field_path.split("."):
        if value is None:
            return None
        value = getattr(value, part)
    if isinstance(value, Stage):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    return value


def _check_turn(turn_index: int, user_input: str, message: str, expect: dict, state) -> Optional[TurnFailure]:
    lower_message = message.lower()

    for phrase in expect.get("message_contains_all", []):
        if phrase.lower() not in lower_message:
            return TurnFailure(
                turn_index, user_input,
                f"expected message to contain {phrase!r} (message_contains_all), but it did not",
                message,
            )

    contains_any = expect.get("message_contains_any")
    if contains_any and not any(p.lower() in lower_message for p in contains_any):
        return TurnFailure(
            turn_index, user_input,
            f"expected message to contain at least one of {contains_any!r} (message_contains_any), but it did not",
            message,
        )

    for phrase in expect.get("message_not_contains", []):
        if phrase.lower() in lower_message:
            return TurnFailure(
                turn_index, user_input,
                f"expected message to NOT contain {phrase!r} (message_not_contains), but it did",
                message,
            )

    for field_name, expected_value in expect.get("state", {}).items():
        actual_value = _resolve_state_value(state, field_name)
        if actual_value != expected_value:
            return TurnFailure(
                turn_index, user_input,
                f"expected state.{field_name} == {expected_value!r}, got {actual_value!r}",
                message,
            )

    return None


def run_test_case(test_case: dict) -> TestCaseResult:
    agent = Agent()
    failures = []
    for i, turn in enumerate(test_case["turns"]):
        result = agent.next(turn["user_input"])
        message = result["message"]
        expect = turn.get("expect", {})
        failure = _check_turn(i, turn["user_input"], message, expect, agent._impl.state)
        if failure:
            failures.append(failure)
            break  # later turns in this case depend on this one; no point continuing
    return TestCaseResult(test_id=test_case["id"], passed=not failures, failures=failures)


def run_phase_file(path: str) -> tuple:
    """Returns (all_passed, total_cases, passed_cases)."""
    with open(path, "r", encoding="utf-8") as f:
        spec = json.load(f)

    print(f"\n{'=' * 70}")
    print(f"Phase {spec.get('phase')}: {spec.get('phase_name')}")
    if spec.get("description"):
        print(f"  {spec['description']}")
    print(f"{'=' * 70}")

    total = 0
    passed_count = 0
    for test_case in spec["test_cases"]:
        total += 1
        result = run_test_case(test_case)
        status = "PASS" if result.passed else "FAIL"
        print(f"\n[{status}] {result.test_id}")
        if test_case.get("description"):
            print(f"    {test_case['description']}")
        if result.passed:
            passed_count += 1
        else:
            for failure in result.failures:
                print(f"    Turn {failure.turn_index} (\"{failure.user_input}\"): {failure.reason}")
                print(f"    Agent said: {failure.actual_message}")

    return (passed_count == total, total, passed_count)


def main() -> int:
    if not os.environ.get("OPENAI_API_KEY"):
        print(
            "OPENAI_API_KEY is not set. This runner calls the real OpenAI "
            "API and the real sandbox payment API -- set the key (or add "
            "it to a .env file, see .env.example) and re-run."
        )
        return 1

    args = sys.argv[1:]
    if not args:
        print("Usage: python eval/run_phase_test.py <phase_test_file.json> [more.json ...]")
        return 1

    paths = []
    for arg in args:
        matched = glob.glob(arg)
        paths.extend(matched if matched else [arg])

    overall_passed = True
    total_cases = 0
    total_passed = 0
    for path in paths:
        file_ok, file_total, file_passed = run_phase_file(path)
        total_cases += file_total
        total_passed += file_passed
        overall_passed = overall_passed and file_ok

    print(f"\n{'=' * 70}")
    print(f"Overall: {total_passed}/{total_cases} test cases passed")
    print(f"{'=' * 70}")
    return 0 if overall_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
