# Phase 5 Test Results — Collect Payment Amount and Card Payment Details

**Assignment step covered:** Step 5 of 8 — *"Collect card payment details."*

**Scope note:** the assignment doesn't give payment-amount collection its
own numbered step, but it happens immediately before card details in the
flow and the assignment explicitly cares about messy amount phrasing (its
own "Payment Amount" example table). This phase's test file covers **both**
amount collection and card-detail collection — everything gathered before
Phase 6's actual `process-payment` call.

**Test file:** [`phase_5_collect_card_details.json`](./phase_5_collect_card_details.json)
**Runner:** [`../run_phase_test.py`](../run_phase_test.py)
**Run command:** `python eval/run_phase_test.py eval/phase_tests/phase_5_collect_card_details.json`

## Methodology

**Live** run: real OpenAI extraction and the real sandbox API for every test
case (card-format validation cases stop before an actual API call, by
design — see test #11). Builds on Phase 4's end state
(`stage: "await_amount"`, identity verified).

## Result: 11/11 test cases passed (after two real issues found and fixed)

| # | Test ID | What it checks | Result |
|---|---|---|---|
| 1 | `amount_specific_number_accepted` | A plain number ("500") is accepted, moves to card collection | ✅ PASS |
| 2 | `amount_worded_phrase_accepted` | Assignment example: "a thousand rupees" → exactly 1000 | ✅ PASS |
| 3 | `amount_partial_payment_phrasing_accepted` | Assignment example: "can I do 500 for now?" → partial payment accepted | ✅ PASS |
| 4 | `amount_full_amount_phrase_resolves_to_exact_balance` | "just clear the full amount" → exact balance, consistent Decimal precision | ✅ PASS |
| 5 | `amount_exceeding_balance_rejected_before_any_card_collection` | Over-balance amount rejected client-side, stays in amount stage | ✅ PASS |
| 6 | `card_details_all_at_once_with_messy_formatting` | Assignment example: spaced number + worded expiry + spoken-digit CVV, all together | ✅ PASS |
| 7 | `card_details_collected_across_multiple_turns_out_of_order` | Card number one turn, CVV+expiry the next — merges correctly | ✅ PASS |
| 8 | `card_details_partial_input_asks_only_for_missing_fields` | Only card number given → asks for exactly CVV + expiry, not the number again | ✅ PASS |
| 9 | `card_number_with_dashes_normalized_correctly` | Dash-separated (not just space-separated) card numbers also normalize | ✅ PASS |
| 10 | `cardholder_name_defaults_to_verified_identity_when_not_specified` | No explicit cardholder name → defaults to the verified account holder | ✅ PASS |
| 11 | `locally_invalid_card_number_rejected_with_retry_countdown_shown` | Luhn-invalid card rejected before any API call, retry count shown | ✅ PASS |

## Two real issues found and fixed during this phase

**1. A card number occasionally got misclassified as an `account_id` too.**
While probing extraction behavior for messy card-number formats, a live
check showed `"4532-0151-1283-0366"` extracted with **both**
`card_number: "4532015112830366"` (correct) **and**
`account_id: "4532015112830366"` (spurious) in the same response — the
model treating a long digit string as plausibly being an account ID even at
the card-collection stage. Impact check: `process_payment()` uses
`state.account.account_id` (the immutable record from lookup), never the
mutable `state.account_id` field, so the actual payment call was never at
risk — but the mutable field itself would have been silently corrupted,
which is a latent footgun for any future code that reads it later in the
flow. **Fix:** `orchestrator.py::_merge_slots` now only accepts an
extracted `account_id` while `self.state.account is None` (i.e. before a
lookup has succeeded) — closing the gap at the source rather than
special-casing "looks like a card number" detection. Unlike the Phase 4
balance-repeat bug (a pure prompt/scope issue), this was a deterministic
code fix, so it also has a permanent offline regression test:
`tests/test_fsm_scripted.py::test_account_id_is_not_overwritten_by_a_stray_extraction_after_lookup_succeeds`.

**2. `state.amount` had inconsistent Decimal precision depending on which
path set it.** A manually-typed amount always goes through
`validators.normalize_amount()`, which quantizes to exactly 2 decimal
places. The "full amount" shortcut (`amount = balance`) did not, so a
balance the API returned as a bare integer-shaped JSON number (e.g. `540`
rather than `540.00`) produced `Decimal("540")` instead of
`Decimal("540.00")` — mathematically identical and *displayed* identically
(`nlg._money()` always forces 2 decimal places), but an internal
inconsistency that a live test assertion caught immediately -- plain
`Decimal` equality doesn't distinguish `Decimal("540")` from
`Decimal("540.00")` (they're equal *by value*), so this required checking
the string representation specifically. **Fix:** the full-amount path now
quantizes to 2 decimal places too, matching `normalize_amount()`'s behavior
exactly. Also has a permanent offline regression test (constructing a fake
account with a bare-int balance to reproduce the exact scenario):
`tests/test_fsm_scripted.py::test_full_balance_phrase_quantizes_to_two_decimal_places_like_a_typed_amount_does`.

Both fixes were verified with a full regression run across Phases 1–4
afterward: **38/38 still passing**, no other behavior affected.

## What this confirms

- **Every messy card/amount phrasing from the assignment's own examples
  works correctly**, including combinations tried nowhere else in this
  project's test suite yet (dash-separated card numbers, "a thousand
  rupees", multi-turn out-of-order card collection).
- **Partial payments are genuinely supported**, not just accepted by
  accident — a specific test explicitly checks an amount less than the
  balance is accepted and processed.
- **Local card validation is a real gate, not a formality** — a
  Luhn-invalid number never reaches the payment API and is rejected with
  the same explicit retry-limit wording as every other retryable failure in
  the system.

## Known limitation of this phase's scope

These tests stop the moment card details are complete and pass local
validation, triggering `process_payment()` — the actual API response
handling (success and every documented failure code) is Phase 6's concern.

## Sign-off

Phase 5 is **verified and ready** (after the two fixes above). Proceeding
to Phase 6 (process the payment via the provided API).
