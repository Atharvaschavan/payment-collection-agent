# Phase 4 Test Results — Share the Outstanding Balance with the Verified User

**Assignment step covered:** Step 4 of 8 — *"Share the outstanding balance
with the verified user."*

**Test file:** [`phase_4_share_balance.json`](./phase_4_share_balance.json)
**Runner:** [`../run_phase_test.py`](../run_phase_test.py)
**Run command:** `python eval/run_phase_test.py eval/phase_tests/phase_4_share_balance.json`

## Methodology

**Live** run: real OpenAI extraction and the real sandbox API. This phase is
narrow by design in this implementation — balance disclosure happens in the
*same* message that confirms verification success (`nlg.verified_share_balance`),
not as a separate step requiring its own round-trip. Tests therefore focus
on three things: (1) the disclosed figure is *exactly* the `Decimal` the
lookup API returned, correctly formatted, for all 4 sandbox accounts
(including the zero-balance special case), (2) it never leaks before
verification actually succeeds, and (3) it stays consistent if referenced
again later in the conversation.

## Result: 6/6 test cases passed (after one real bug found and fixed)

| # | Test ID | What it checks | Result |
|---|---|---|---|
| 1 | `balance_disclosed_in_same_turn_as_verification_acc1001` | ₹1,250.75 (comma + decimal) disclosed in the same message as "identity verified" | ✅ PASS |
| 2 | `balance_formatted_correctly_as_whole_number_acc1002` | ₹540.00 renders with 2 decimal places, not truncated to ₹540 | ✅ PASS |
| 3 | `balance_formatted_correctly_half_rupee_acc1004` | ₹3,200.50 renders exactly | ✅ PASS |
| 4 | `zero_balance_disclosed_and_closes_cleanly_acc1003` | ₹0.00 disclosed, conversation closes cleanly, never asks "how much would you like to pay" | ✅ PASS |
| 5 | `balance_not_disclosed_before_verification_succeeds` | Balance absent from both a wrong attempt and a partial-input prompt | ✅ PASS |
| 6 | `balance_figure_stays_consistent_between_verification_and_amount_prompt` | Asking to be reminded of the balance later gets the same figure back, not a decline | ✅ PASS |

## A real bug found and fixed during this phase

While writing test #6, a live check surfaced a genuine bug: asking *"how
much do I owe again, remind me?"* after verification got the response
*"For security reasons, I'm not able to repeat identifying information back
to you..."* — the agent **declined to share the user's own balance**, which
directly contradicts this phase's whole purpose (the assignment explicitly
wants the balance shared with the verified user) and is not something the
assignment classifies as sensitive (only DOB, Aadhaar, and pincode are named
as sensitive — balance is not on that list).

**Root cause:** the `wants_info_repeated` extraction flag (added during the
Phase 1 security hardening) was too broad — it correctly caught requests to
repeat *identity* fields (account ID, DOB, Aadhaar, pincode, card details),
but nothing in its definition excluded balance/amount-owed questions, so the
model applied the same "decline for security" behavior to a completely
different, legitimate kind of request.

**Fix:** narrowed the field's schema description and added an explicit
carve-out in the extraction system prompt (`payment_agent/extraction.py`)
stating that balance/amount-owed questions are never `wants_info_repeated`,
since the balance is meant to be freely (re)shared with a verified user.
Verified 3/3 consistent correct responses after the fix — the request now
falls through to the existing `_handle_amount()` path, which already
restates the balance as part of asking how much to pay, so **no new code
path was needed, only a scope correction to the existing one.** Re-ran
Phases 1–3 afterward as a regression check: 32/32 still passing, no other
behavior affected.

This is the third real, live-verified extraction issue found across this
project's phase-by-phase testing (after the "wait," cancellation
misread in Phase 1, and the "not sure what my account id is"
misread caught before Phase 2's tests were finalized) — each one was a
scope/disambiguation problem in a boolean flag's definition, not a logic
bug in the deterministic code, and each was caught specifically because a
concrete test scenario was tried live rather than assumed to work from
reading the prompt.

## What this confirms

- **Balance formatting is exact across whole-number, comma, and half-rupee
  cases** — not just "a number appears somewhere in the message."
- **The zero-balance path (ACC1003) really is "sharing the balance"** in
  this design, not a separate concern — ₹0.00 is disclosed and the
  conversation closes in the same step, consistent with DESIGN.md §4.6.
- **No premature disclosure.** The balance is genuinely gated on
  `verification.Outcome.SUCCESS`, not just usually absent before that point.
- **Balance requests are correctly distinguished from sensitive-data
  requests** now, closing the gap the bug above exposed.

## Known limitation of this phase's scope

These tests don't cover amount *collection* (a specific number, "full
amount" phrasing, partial payments) — that's Phase 5's concern, which picks
up from the `stage: "await_amount"` state this phase's successful cases
leave behind.

## Sign-off

Phase 4 is **verified and ready** (after the fix above). Proceeding to
Phase 5 (collect card payment details).
