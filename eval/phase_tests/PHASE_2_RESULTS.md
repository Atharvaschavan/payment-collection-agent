# Phase 2 Test Results — Look Up the Account via the Provided API

**Assignment step covered:** Step 2 of 8 — *"Look up the account via the
provided API."*

**Test file:** [`phase_2_account_lookup.json`](./phase_2_account_lookup.json)
**Runner:** [`../run_phase_test.py`](../run_phase_test.py)
**Run command:** `python eval/run_phase_test.py eval/phase_tests/phase_2_account_lookup.json`

## Methodology

**Live** run: real OpenAI extraction (`gpt-4.1-nano`) and a real call to
`POST /api/lookup-account` against the sandbox API for every test case — no
fakes or mocks. Builds on the state Phase 1 leaves the agent in
(`stage: "await_account_id"`, `account_id: null`), and checks: (1) that the
lookup API is actually invoked and its response correctly populates
`ConversationState.account`, (2) that no sensitive account field ever
appears in a user-facing message at this phase, and (3) that both kinds of
lookup failure (a well-formatted but nonexistent ID, and a locally-invalid
format) are handled correctly and distinctly — the assignment's own
"Validate all inputs before calling any API" and "sensible retry limit"
requirements applied specifically to lookup.

The runner was extended for this phase to support one level of dotted-path
state assertions (e.g. `"account.full_name"`), since `state.account` is a
nested `AccountRecord` populated only once a lookup succeeds — see
`run_phase_test.py::_resolve_state_value`.

## Result: 9/9 test cases passed (first live run, no fixes needed)

| # | Test ID | What it checks | Result |
|---|---|---|---|
| 1 | `lookup_acc1001_succeeds` | ACC1001 → account data stored correctly, moves to identity collection, no sensitive data leaked | ✅ PASS |
| 2 | `lookup_acc1002_succeeds` | ACC1002 → same, confirms the integration isn't hardcoded to one account | ✅ PASS |
| 3 | `lookup_acc1003_succeeds` | ACC1003 (zero-balance account) → looks up correctly at this phase; the zero-balance *closure* logic is a later phase's concern | ✅ PASS |
| 4 | `lookup_acc1004_succeeds` | ACC1004 (leap-year-DOB account) → looks up correctly | ✅ PASS |
| 5 | `messy_phrasing_still_looks_up_correctly` | "it's ACC 1001" → normalizes correctly *and* the real API call actually retrieves the right account (not just superficial state advancement) | ✅ PASS |
| 6 | `nonexistent_account_asks_again_and_counts_as_one_attempt` | ACC9999 (real 404) → asks user to double-check, counts as 1 attempt, stays open | ✅ PASS |
| 7 | `invalid_format_account_id_does_not_count_as_a_lookup_attempt` | "my account is XYZ1001" (fails format check, API never called) → does **not** count against the retry limit | ✅ PASS |
| 8 | `three_nonexistent_accounts_exhaust_the_retry_limit` | 3× nonexistent IDs → closes cleanly at exactly 3 attempts | ✅ PASS |
| 9 | `uncertain_about_own_account_id_is_not_misread_as_a_repeat_request` | Regression guard (see below) | ✅ PASS |

## What this confirms

- **The real `lookup-account` API is called correctly and its data is used
  correctly**, for all 4 sandbox test accounts, not just one — each
  `account.full_name` assertion is checked against the real API response,
  not a scripted stand-in.
- **No sensitive data leaks at this phase.** Balance, DOB, Aadhaar, and
  pincode are all confirmed absent from every message in tests #1–2 (and
  implicitly throughout, since the agent's response text is entirely
  templated — see DESIGN.md §4.3 — so this is really confirming the
  *lookup* step doesn't trigger premature disclosure, not re-testing the
  templates themselves).
- **Retry accounting is precise, not approximate.** A locally-invalid
  format (#7) correctly does *not* consume a retry, while a real 404 (#6,
  #8) does — and the limit closes at exactly 3, not before or after. This
  distinction matters: without it, a user who mistypes the "ACC" prefix
  entirely would burn through their real attempts on the API for a mistake
  the client should have caught first.
- **Messy phrasing survives the full round trip**, not just extraction: #5
  confirms "it's ACC 1001" doesn't just *parse* to `ACC1001` (already shown
  in Phase 1) but that the resulting API call actually retrieves the
  correct account record.

## Regression guard included in this phase

Test #9 (`uncertain_about_own_account_id_is_not_misread_as_a_repeat_request`)
is a deliberate regression guard for the extraction bug found and fixed
during the Phase 1 security addition (see `PHASE_1_RESULTS.md`): *"I'm not
sure what my account id is"* was, before that fix, at risk of being
misclassified given how aggressively the model had started pattern-matching
uncertainty language. This phase confirms the fix generalizes correctly to
a slightly different, still-plausible real phrasing at a different point in
the flow (before any account ID has been given at all, vs. after).

## Known limitation of this phase's scope

These tests stop the moment lookup succeeds or exhausts — they do not touch
identity verification (Phase 3), which begins from the
`stage: "await_identity"` state this phase's successful cases leave behind.

## Sign-off

Phase 2 is **verified and ready**. Proceeding to Phase 3 (collect identity
information and verify the user).
