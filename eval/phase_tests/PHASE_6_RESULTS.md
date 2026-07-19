# Phase 6 Test Results — Process the Payment via the Provided API

**Assignment step covered:** Step 6 of 8 — *"Process the payment via the
provided API."*

**Test file:** [`phase_6_process_payment.json`](./phase_6_process_payment.json)
**Runner:** [`../run_phase_test.py`](../run_phase_test.py)
**Run command:** `python eval/run_phase_test.py eval/phase_tests/phase_6_process_payment.json`

## Methodology

**Live** run: real OpenAI extraction and a real `POST /api/process-payment`
call against the sandbox API for every test case. Builds on Phase 5's end
state (card details collected and locally validated).

**Scope note:** the assignment documents 5 API-level failure codes for this
endpoint (`invalid_card`, `invalid_cvv`, `invalid_expiry`, `invalid_amount`,
`insufficient_balance`). All 5 are, **by design**, unreachable through a
normal conversation — client-side validation (`validators.py`) rejects
malformed cards/CVVs/expiries/amounts before any API call is made, per the
assignment's own "validate all inputs before calling any API" requirement.
So this phase splits its verification in two:

1. **Live conversational coverage** (`phase_6_process_payment.json`) —
   what a real conversation actually exercises: successful payments (full
   and partial amount, multiple accounts), real unique transaction IDs, and
   correct session closure afterward.
2. **Direct-to-API contract verification** (bypassing the `Agent`, calling
   `api_client.py` directly against the real sandbox) — to check the
   documented error codes actually match what the live API returns, since
   client-side validation means these codes can never be observed through
   the conversational flow. This is where the real issue below was found.

## Result: 4/4 live test cases passed (after one critical issue found and fixed)

| # | Test ID | What it checks | Result |
|---|---|---|---|
| 1 | `payment_processes_successfully_full_amount` | ACC1002 full-balance payment succeeds, real transaction ID appears in confirmation + recap | ✅ PASS |
| 2 | `payment_processes_successfully_partial_amount` | ACC1001 partial payment (500 of 1,250.75) succeeds against the real API, not just accepted locally | ✅ PASS |
| 3 | `payment_processes_successfully_acc1004_leap_year_account` | Payment succeeds on a second account, confirming the path isn't account-specific | ✅ PASS |
| 4 | `conversation_stops_processing_further_input_after_successful_payment` | Further input after a successful payment gets a fixed closing reply, no re-engagement of the LLM or a second payment attempt | ✅ PASS |

## Critical issue found and fixed during this phase

**The real sandbox API does not return the documented per-field error codes
for a bad CVV or an expired card.** Direct verification against the live
API (calling `api_client.py::process_payment` directly, bypassing the
`Agent` and its client-side validation) showed:

- A wrong-length CVV and an expired card **both** return HTTP **400** with
  `error_code: "invalid_args"` — not the documented `"invalid_cvv"` /
  `"invalid_expiry"` (which the assignment describes as HTTP 422).
- `invalid_card`, `invalid_amount`, and `insufficient_balance` matched the
  documented contract when tested directly.

Without a fix, `"invalid_args"` would have fallen through
`orchestrator.py`'s error handling to the **terminal failure** branch
(`payment_terminal_failure`, immediate session close) instead of the
**retryable** branch — directly violating the assignment's explicit
requirement to "distinguish user-fixable errors (retry) from terminal
errors (end conversation)." A bad CVV or a typo'd expiry date is about as
user-fixable as an error gets, so silently treating it as terminal would
have been a significant correctness bug, and one invisible to conversational
testing alone since client-side validation prevents ever reaching it that
way live.

**Fix:**
- Added `"invalid_args"` to `RETRYABLE_CARD_ERRORS` in `orchestrator.py`.
- Added a card-clearing branch in `_handle_payment_error()` for
  `invalid_args` (clears `state.pending_card` so the user is asked to
  re-enter all card fields, matching the treatment for the other three
  retryable card errors).
- Added NLG text (`PAYMENT_ERROR_TEXT["invalid_args"]` in `nlg.py`):
  *"one or more of your card details appear to be invalid"* — deliberately
  generic since the API doesn't tell us which field was actually wrong.
- Added two permanent offline regression tests, since this scenario cannot
  be exercised through the live conversational `Agent` flow by design:
  - `tests/test_fsm_scripted.py::test_invalid_args_error_code_is_treated_as_retryable_not_terminal`
    — verifies the whole card is cleared, the "2 of 3 attempts remaining"
    wording is shown, and the session is **not** closed.
  - `tests/test_api_client.py::test_process_payment_invalid_args_error_code`
    — verifies the HTTP client surfaces the 400/`invalid_args` response
    correctly regardless of status code.

Both offline suites pass fully after the fix (60/60 unit tests), and a full
regression run across Phases 1–5 afterward confirmed nothing else broke:
**49/49 still passing.**

## What this confirms

- **Successful payments work correctly end-to-end** against the real API —
  full amounts, partial amounts, and multiple accounts all produce genuine,
  unique transaction IDs that appear correctly in both the immediate
  confirmation and the closing recap.
- **The session correctly and permanently closes after a successful
  payment** — no further processing, no re-engaging the LLM, no risk of a
  double charge from continued input.
- **The assignment's documented error-code table is not fully accurate for
  this sandbox**, and only direct-to-API verification (not conversational
  testing, and not blind trust in the spec) caught it. This is exactly the
  kind of gap that client-side validation is good at hiding from
  conversational testing — it had to be checked directly against the real
  API to surface at all.
- **The architecture's LLM/logic separation held up again** — this was a
  pure orchestrator/NLG fix; `extraction.py` was untouched.

## Known limitation of this phase's scope

The other 4 documented error codes (`invalid_card`, `invalid_amount`,
`insufficient_balance`, and whichever code truly maps to a validation
scenario not superseded by `invalid_args`) remain untestable through a live
conversation by design — client-side validation is working as intended by
rejecting them first. Their handling is verified via `FakeAPIClient` in
`tests/test_fsm_scripted.py` and directly against the client in
`tests/test_api_client.py`, not via `run_phase_test.py`.

## Sign-off

Phase 6 is **verified and ready** (after the `invalid_args` fix above).
Proceeding to Phase 7 (communicate the outcome clearly to the user).
