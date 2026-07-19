# Phase 3 Test Results — Collect Identity Information and Verify the User

**Assignment step covered:** Step 3 of 8 — *"Collect identity information
and verify the user (see Verification Requirements)."*

**Test file:** [`phase_3_identity_verification.json`](./phase_3_identity_verification.json)
**Runner:** [`../run_phase_test.py`](../run_phase_test.py)
**Run command:** `python eval/run_phase_test.py eval/phase_tests/phase_3_identity_verification.json`

## Methodology

**Live** run: real OpenAI extraction (`gpt-4.1-nano`) and the real
`lookup-account` API for every test case. Builds on Phase 2's end state
(`stage: "await_identity"`, account already looked up). This phase maps
directly onto the assignment's own Verification Requirements section, so
each test case is written to correspond to one specific requirement rather
than being a general smoke test — see the table below.

## Result: 14/14 test cases passed (first live run, no fixes needed)

| # | Test ID | Verification Requirement it checks | Result |
|---|---|---|---|
| 1 | `verify_with_dob_succeeds` | Name + DOB → verifies, moves to amount stage | ✅ PASS |
| 2 | `verify_with_aadhaar_succeeds` | Name + Aadhaar last 4 (any ONE secondary factor suffices) | ✅ PASS |
| 3 | `verify_with_pincode_succeeds` | Name + pincode (any ONE secondary factor suffices) | ✅ PASS |
| 4 | `verify_lowercase_name_fails_no_case_insensitive_workaround` | **"Matching is strict — no fuzzy matching, no case-insensitive workaround for names"** — a lowercased name fails even with an otherwise-correct secondary factor | ✅ PASS |
| 5 | `verify_name_only_asks_for_secondary_without_consuming_a_retry` | **"Handle partial inputs gracefully"** — name only → asks for secondary, no attempt consumed | ✅ PASS |
| 6 | `verify_secondary_only_asks_for_name_without_consuming_a_retry` | Secondary only → asks for name, no attempt consumed | ✅ PASS |
| 7 | `verify_wrong_secondary_with_correct_name_fails_and_counts_as_one_attempt` | A *complete* wrong claim counts as exactly one attempt (contrast with #5/#6) | ✅ PASS |
| 8 | `verify_exhausts_all_three_attempts_and_closes` | **"Allow reasonable retries but implement a sensible retry limit"** — closes at exactly 3 | ✅ PASS |
| 9 | `verify_leap_year_dob_exact_match_succeeds` | ACC1004 leap-year DOB (1988-02-29) verifies correctly | ✅ PASS |
| 10 | `verify_leap_year_dob_nearby_wrong_date_is_an_ordinary_mismatch` | A valid-but-wrong nearby date is an ordinary mismatch, not a format error | ✅ PASS |
| 11 | `verify_impossible_date_flagged_before_being_treated_as_a_mismatch` | A non-existent date (1990-02-29) is flagged as invalid *before* verification, and doesn't consume a retry | ✅ PASS |
| 12 | `verify_all_info_given_at_once_out_of_order_succeeds_in_one_turn` | Out-of-order/combined input verifies in one turn, no forced round-trips | ✅ PASS |
| 13 | `security_never_exposes_dob_aadhaar_pincode_across_a_full_verification_attempt_cycle` | **"Do not expose account data (DOB, Aadhaar, pincode) to the user during or after verification"** — checked across a fail, a partial prompt, and a success | ✅ PASS |
| 14 | `security_declines_to_repeat_dob_back_after_giving_it` | Phase 1's "don't repeat sensitive info on request" security addition extended to DOB | ✅ PASS |

## What this confirms

- **Every clause of the assignment's Verification Requirements section has a
  corresponding test**, not just a general "verification works" smoke test:
  strict matching (#4), any-one-of-three secondary factors (#1–3), graceful
  partial-input handling (#5–6), correct retry counting that distinguishes
  "incomplete" from "wrong" (#7), the retry limit (#8), and non-disclosure
  of sensitive data (#13) are each independently checked.
- **The strictness requirement is the one most worth over-testing**, since
  it's explicitly called out as a hard rule with a specific failure mode
  named ("no case-insensitive workaround") — #4 checks exactly that failure
  mode directly, live, rather than trusting that strict `==` comparison in
  `verification.py` "obviously" generalizes to the live case.
- **The leap-year edge case (ACC1004) is fully covered in the phase where it
  actually matters** — verification — in all three of its meaningful forms,
  matching the assignment's own explicit note about it.
- **No sensitive data appeared in any message across a fail → partial →
  success cycle** (#13), and the agent declines to repeat back a DOB the
  user themselves just provided (#14) — both live-verified, not just
  asserted from reading the templates in `nlg.py`.
- **Zero flakiness on this run** — all 14 passed first try, despite the
  known extraction-variance risk documented in `EVALUATION.md` (which was
  observed on other runs/scenarios, not eliminated, just not triggered
  here). That risk remains a documented, accepted limitation per the
  decision to leave it as-is rather than add mitigation complexity right
  now.

## Known limitation of this phase's scope

These tests stop the moment verification succeeds or exhausts — they do not
touch balance disclosure wording beyond confirming it appears (Phase 4),
amount collection, or payment (Phases 5–6). The zero-balance account
(ACC1003) is deliberately not re-tested here since its special handling is
already covered by `tests/test_fsm_scripted.py` and is really an
amount-stage concern (DESIGN.md §4.6), not a verification-stage one --
verification behaves identically regardless of balance.

## Sign-off

Phase 3 is **verified and ready**. Proceeding to Phase 4 (share the
outstanding balance with the verified user).
