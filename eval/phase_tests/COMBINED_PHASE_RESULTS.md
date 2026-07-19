# Combined-Phase Test Results — All 8 Steps in One Continuous Conversation, Context Retention Focus

**What this file is for:** Phases 1-8 each verified one step of the
assignment's problem statement in isolation, with a fresh `Agent` per test
case. That's deliberate (it keeps failures attributable to a single step),
but it also means no prior test file ever proves the *whole* journey holds
together end-to-end in one session, or that information given early
genuinely survives every stage transition between when it's given and when
it's actually used. This file closes that gap.

**Test file:** [`combined_all_phases_journey.json`](./combined_all_phases_journey.json)
**Runner:** [`../run_phase_test.py`](../run_phase_test.py)
**Run command:** `python eval/run_phase_test.py eval/phase_tests/combined_all_phases_journey.json`

## Methodology

**Live**, real OpenAI extraction, real sandbox API, exactly as in every
other phase file — but each test case here is one single, uninterrupted
`Agent` instance run through *all* applicable steps of the assignment
(greet → lookup → verify → share balance → collect amount → collect card →
process payment → communicate outcome → recap and close), not just one.

Assertions lean heavily on `message_not_contains` (proving the agent never
re-asks for something already given, however many turns earlier) and
dotted `state` paths like `account.full_name` (proving data from the
lookup API is still correctly attached many turns after the call that
fetched it) — context retention is the thing being tested, not just
step-by-step correctness, which the other 8 files already cover.

Run **twice** in full to check for the LLM extraction non-determinism
already documented in `eval/EVALUATION.md` (§ Observations) — both runs
passed identically.

## Result: 4/4 test cases passed, on both runs — no issues found

| # | Test ID | What it stresses | Result (run 1 / run 2) |
|---|---|---|---|
| 1 | `full_journey_clean_linear_all_8_steps` | Baseline: all 8 steps complete correctly in one session; the final message doesn't re-ask for the account ID or name given 4 turns earlier | ✅ PASS / ✅ PASS |
| 2 | `full_journey_early_volunteered_card_survives_identity_and_amount_stages` | A card number volunteered in the very first turn (alongside the account ID) survives two full stage transitions (identity verification, amount collection) untouched, and is the number actually charged — while the agent still asks for identity next rather than skipping ahead | ✅ PASS / ✅ PASS |
| 3 | `full_journey_everything_after_lookup_volunteered_in_one_message_but_steps_are_not_skipped` | The most compressed message in this project: identity + amount + full card details all volunteered in one turn. Confirms the hard rule "do NOT skip steps even if the user volunteers information early" holds (verification completes and balance is shared *before* any payment attempt) while none of the volunteered payment data is lost — the very next turn completes the payment with zero re-prompting | ✅ PASS / ✅ PASS |
| 4 | `full_journey_zero_balance_account_context_carried_through_shortened_flow` | A structurally shorter journey (ACC1003 has nothing to pay, so steps 5-7 never happen) still correctly carries the account ID and name through to the final close message | ✅ PASS / ✅ PASS |

No real issues were found or fixed while building this file. The result is
a genuine (not assumed) confirmation that `orchestrator.py`'s slot-merging
design — merging every extracted field into `ConversationState`
unconditionally in `_merge_slots()`, regardless of what stage the
conversation is currently in, and only ever *acting* on a field once its
stage is reached — is what makes both properties true simultaneously:
nothing volunteered early is lost, and nothing is ever skipped ahead of
schedule.

## What this confirms, that no single-phase file could

- **State survives arbitrarily many stage transitions**, not just the one
  transition each phase file happens to cross. Test #2's card number is
  merged at turn 1 and not read again until turn 4, after both the
  identity-verification and amount-collection stages have come and gone.
- **Early-volunteered information is retained but never used to skip a
  step.** Test #3 is the sharpest version of this: a single message
  contains everything needed to go straight to a successful payment, and
  the agent still visibly performs verification and balance-disclosure
  first, in a separate turn, before the payment is processed one turn
  later purely from already-held state (no re-prompt, no re-statement from
  the user). This is a direct, live demonstration of the assignment's hard
  rule "Do NOT skip steps even if the user volunteers information early" —
  under the most adversarial input this project has thrown at it.
- **The zero-balance short path (ACC1003) isn't a special-cased hack that
  happens to work alone** — it correctly carries context (the looked-up
  name) into its own final message just like the three full-length
  journeys do.
- **Two consecutive full live runs produced identical results**, which is
  the strongest confidence this project has yet built that the specific
  behaviors checked here are not a one-off lucky extraction, given the
  extraction-variance risk already documented in `EVALUATION.md`.

## Addendum: does retention hold across the LLM's 16-message transcript cap?

`config.MAX_HISTORY_MESSAGES_FOR_EXTRACTION = 16` bounds how much raw
dialogue is replayed to the LLM extractor each turn (`orchestrator.py::
_record_turn` trims the oldest messages once the cap is exceeded) — a
deliberate cost/latency bound, documented in `DESIGN.md` §4.1. Every test
above stays under 8 turns (16 messages), so none of them actually cross
this boundary. That gap is closed by
[`context_window_boundary_test.json`](./context_window_boundary_test.json):
an 11-turn conversation where a card number is volunteered at turn 1 (in
the same message as the account ID) and not actually needed until turns
10-11 — well past the point where turn 1's raw text has mathematically
been evicted from what's replayed to the LLM. 6 filler/off-topic turns
(safety questions, "one moment", asking about the retry limit) are used to
burn turns between account lookup and identity verification without ever
forming a complete, wrong identity claim, so none of them cost a
verification attempt.

**Result: 1/1 passed.** Direct instrumentation (bypassing the JSON runner
to print internal state after every turn) confirms the mechanics exactly:

| Turn | Transcript length | Turn 1's card text still in transcript? | `card_number` in state |
|---|---|---|---|
| 1 | 2 | True | `4532015112830366` |
| 2-7 | 4, 6, 8, 10, 12, 14 | True | `4532015112830366` |
| 8 | 16 (cap reached) | True | `4532015112830366` |
| 9 | 16 (capped) | **False — evicted** | `4532015112830366` |
| 10 | 16 (capped) | False | `4532015112830366` |
| 11 | 16 (capped) | False | `None` (cleared post-payment, by design) |

Turn 1's raw sentence is gone from the transcript replayed to the LLM by
the time turn 9 finishes recording — meaning turn 10's extraction call is
made with **zero visibility** into the message that originally supplied the
card number. Turn 10 still correctly treats the card number as already
known (asking only for CVV and expiry, never re-asking for the card
number), and turn 11 charges that exact number successfully. This is
proof by direct observation, not inference: retention across the whole
conversation does not depend on the LLM ever "remembering" anything —
`_merge_slots()` writes extracted fields straight into permanent
`ConversationState` attributes the moment they're first seen, and nothing
downstream ever re-derives them from the transcript again. The transcript
cap only limits what the LLM can *newly interpret* about old phrasing
(e.g. resolving a correction to something said 20 turns ago); it has no
effect on facts already captured into state.

(`card_number` becoming `None` at turn 11 is expected, not a bug —
`_close_success()` clears `pending_card` after a successful payment per
the assignment's "do not store or log raw card data beyond what is
necessary for the API call" requirement.)

## Known limitation of this file's scope

This file only exercises *successful* journeys end-to-end — it deliberately
does not re-test retryable/terminal failure paths (Phases 2, 3, 6, 7 own
that), since mixing failure-path assertions into an already-long
continuous conversation would make failures harder to attribute to a
specific cause. It is a complement to the 8 phase files, not a replacement
for any of them.

## Sign-off

All 8 assignment steps have now been verified both in isolation (Phases
1-8, 62/62) and as one continuous, realistic user journey with an explicit
focus on context retention (this file, 4/4 on two separate live runs).
Combined with the 60/60 offline suite, the project has **66 live test
cases** and **126 total tests** passing.
