# Phase 7 Test Results — Communicate the Outcome Clearly

**Assignment step covered:** Step 7 of 8 — *"Communicate the outcome
clearly (success with transaction ID, or failure with reason)."*

**Test file:** [`phase_7_communicate_outcome.json`](./phase_7_communicate_outcome.json)
**Runner:** [`../run_phase_test.py`](../run_phase_test.py)
**Run command:** `python eval/run_phase_test.py eval/phase_tests/phase_7_communicate_outcome.json`

## Methodology

**Live** run: real OpenAI extraction and (where reached) the real
`process-payment` API.

**Scope note:** the *success* half of this step (transaction ID + outcome
in one message) was already verified in Phase 6
(`payment_processes_successfully_*` test cases) — `nlg.payment_success()`
folds the transaction ID and the outcome into a single response, so there
was nothing left to test there. This phase focuses on the *failure* half,
scoped to what a live conversation can actually reach: the 5 documented
`process-payment` API error codes remain unreachable live by design
(client-side validation rejects malformed input before any API call is
made — see Phase 6's scope note), so this phase instead exercises the
failure paths a real user genuinely triggers: local card-field rejection
with a specific reason, exhausting the shared payment-attempt retry limit,
and cancelling mid-flow.

## Result: 4/4 test cases passed — no new issues found

| # | Test ID | What it checks | Result |
|---|---|---|---|
| 1 | `cancellation_mid_flow_communicates_clear_outcome_and_closes` | Cancelling mid-flow gets an explicit cancellation message (not a generic error or silent stall) and closes immediately with `close_reason: "user_cancelled"` | ✅ PASS |
| 2 | `invalid_cvv_rejected_with_specific_reason_and_retry_count` | A wrong-length CVV is named specifically as the problem (not a generic card error), with an explicit "2 of 3 attempts remaining" | ✅ PASS |
| 3 | `invalid_expiry_rejected_with_specific_reason_and_retry_count` | An already-expired date is named specifically as the problem, with an explicit retry count | ✅ PASS |
| 4 | `three_invalid_card_entries_exhaust_payment_attempts_with_clear_terminal_message` | Three consecutive invalid card numbers exhaust `MAX_PAYMENT_ATTEMPTS`, closing with a message that states both the reason *and* that the retry limit was reached | ✅ PASS |

No real issues were found or fixed during this phase — every code path
exercised here (`_reject_card_field`, the `wants_to_stop` short-circuit in
`next()`, and the card-field-specific messages in `nlg.py`) had already
been built out and, in the case of the retry-limit wording, previously
regression-tested during earlier phases. This phase's value is in
confirming those paths hold up under live LLM extraction end-to-end,
including through to actual exhaustion, which prior phases hadn't pushed
this specific path (card-field rejection) all the way to.

## What this confirms

- **Failure reasons are specific, not generic.** A bad CVV is described as
  a CVV problem, and a bad expiry as an expiry problem — the user is never
  left guessing which field to fix, matching the assignment's "distinguish
  user-fixable errors" requirement at the level of *which field*, not just
  *whether* it's fixable.
- **The payment-attempt retry limit is real and shared** across repeated
  local card-validation failures, not just API-level failures — three bad
  card numbers in a row genuinely close the session, with the same
  explicit "reached the retry limit" language used everywhere else in the
  system.
- **Cancellation is treated as a first-class outcome**, not an escape
  hatch that leaves the session in an ambiguous state — it gets its own
  clear message and an immediate, deliberate close.

## Known limitation of this phase's scope

As in Phase 6, the 5 documented API-level failure codes
(`invalid_card`, `invalid_cvv`, `invalid_expiry`, `invalid_amount`,
`insufficient_balance`) plus the previously-discovered `invalid_args`
sandbox quirk cannot be triggered through a live conversation — client-side
validation is working as intended by catching them first. Their message
correctness is verified via `FakeAPIClient` in
`tests/test_fsm_scripted.py`.

## Sign-off

Phase 7 is **verified and ready**. Proceeding to Phase 8 (recap and close
the conversation).
