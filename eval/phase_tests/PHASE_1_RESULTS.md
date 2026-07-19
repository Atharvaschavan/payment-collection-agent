# Phase 1 Test Results — Greet the User and Prompt for Account ID

**Assignment step covered:** Step 1 of 8 — *"Greet the user and prompt for
their account ID."*

**Test file:** [`phase_1_greeting.json`](./phase_1_greeting.json)
**Runner:** [`../run_phase_test.py`](../run_phase_test.py)
**Run command:** `python eval/run_phase_test.py eval/phase_tests/phase_1_greeting.json`

## Methodology

This is a **live** run: every test case creates a fresh `Agent()` and calls
`agent.next(user_input)` for real — real OpenAI extraction (`gpt-4.1-nano`),
no fakes or mocks anywhere in this run. Each test case checks turn 1 only
(this phase is, by definition, the agent's very first response), asserting
both the message text (via case-insensitive substring checks) and the
resulting internal state (`ConversationState` fields like `stage`,
`account_id`, `closed`).

Scope, deliberately narrow: these tests check *only* that the agent greets
and asks for an account ID appropriately on the first turn. They do not
touch account lookup, verification, or anything past turn 1 — that begins
in Phase 2.

## Result: 9/9 test cases passed

| # | Test ID | What it checks | Result |
|---|---|---|---|
| 1 | `bare_greeting` | Plain "Hi" → greets and asks for account ID | ✅ PASS |
| 2 | `different_greeting_wording` | "Hello there!" → same behavior, wording-independent | ✅ PASS |
| 3 | `casual_opening_not_a_greeting_word` | "hey, I need to make a payment on my account" → doesn't get derailed, still asks for account ID | ✅ PASS |
| 4 | `question_as_first_message` | "Hi, what information do you need from me?" → doesn't try to answer the question, asks for account ID | ✅ PASS |
| 5 | `chitchat_first_message` | "Hey, how's it going?" → pure chit-chat doesn't derail the flow | ✅ PASS |
| 6 | `minimal_lowercase_input` | "hi" (minimal, lowercase, unpunctuated) → handled identically | ✅ PASS |
| 7 | `boundary_account_id_volunteered_in_first_message` | "Hi, my account is ACC1001" → still greets, but does **not** redundantly re-ask for the account ID since it was already given | ✅ PASS |
| 8 | `messy_account_id_formatting_lowercase_with_space` | "acc 1001" (lowercase, spaced) as the very first message → normalized to `ACC1001`, looked up successfully | ✅ PASS |
| 9 | `security_declines_to_repeat_account_id` | Account ID given, then user asks the agent to repeat it back → agent declines citing security, never echoes "ACC1001" | ✅ PASS |

## What this confirms

- **The greeting is content-independent.** Regardless of whether the user's
  opening message is a greeting, a question, chit-chat, or a casual
  statement, the agent's first reply always includes a greeting and a
  request for the account ID (unless the ID was already given — see #7).
  This is the deterministic behavior guaranteed by
  `orchestrator.py`'s `first_turn` handling (`nlg.GREETING_PREFIX` is
  prepended to whatever the turn-1 response would otherwise be), not
  something left to the LLM to decide.
- **The agent doesn't get derailed by off-topic turn-1 input.** A question
  ("what information do you need from me?") or chit-chat doesn't cause the
  agent to try to answer it or lose track of what it needs — real OpenAI
  extraction correctly classified these without special-casing, and the
  deterministic state machine ignores irrelevant extracted intent when
  `account_id` is still missing.
- **Out-of-order input is honored, not ignored.** When the account ID is
  volunteered immediately (#7), the agent does not force a redundant
  "please share your account ID" round-trip — it acknowledges and moves
  toward lookup in the same turn. (Note: this specific case therefore also
  exercises a sliver of Phase 2's account-lookup logic, since the two are
  chained in the same turn by design — see DESIGN.md §3. It's included here
  because it's fundamentally a *turn-1* behavior question.)
- **Messy account-ID formatting is normalized correctly, even as the very
  first message.** "acc 1001" (lowercase, with a space — one of the
  assignment's own example phrasings) is correctly normalized to `ACC1001`
  and looked up successfully (#8), confirming the LLM-driven normalization
  (DESIGN.md §4.1) works on turn 1, not just in later turns.
- **The agent never repeats identifying information back on request.** This
  was added as a deliberate security hardening, beyond what the assignment
  explicitly requires for account IDs specifically (only DOB/Aadhaar/pincode
  are named as sensitive in the brief) -- but the same "don't expose
  identifying data" principle was extended here on request. Implementation:
  a new `wants_info_repeated` extraction flag, checked in
  `orchestrator.py::next()` as a hard short-circuit before any stage routing
  runs, so it can never reach a code path that might interpolate the
  account ID (or, in later phases, DOB/Aadhaar/pincode/card data) into a
  response. See `payment_agent/nlg.py::decline_repeat_request()`.

## A real bug found and fixed during this addition

The first live run of `security_declines_to_repeat_account_id` (test #9
today; it was the last test added at the time, so 8/8 in the file as it
existed then) **failed**: for the input *"wait, can you repeat my account ID
back to me?"*, the model classified `wants_to_stop` as `true` (misreading
the hesitation opener "wait," as wanting to cancel) and the agent responded
with `"No problem -- I've cancelled this session."` instead of declining to
repeat. This is exactly the kind of real, non-hypothetical extraction issue
that live testing (vs. the offline fake-based suite) is designed to surface
— the offline tests, which script the extraction result directly, could not
have caught this.

**Fix:** added explicit disambiguation to the extraction system prompt
(`payment_agent/extraction.py::SYSTEM_PROMPT`) clarifying that hesitation
openers ("wait,", "hold on,", "actually,") do not by themselves mean
cancellation, and that `wants_to_stop` and `wants_info_repeated` are
independent, mutually compatible flags. Re-tested 3/3 consistent correct
classifications after the fix, then re-ran the full test file: passing.
See DESIGN.md and `eval/EVALUATION.md` for the broader pattern (this is the
second real, live-verified extraction issue found this way, after the
model-availability issue found during the Gemini→OpenAI provider swap).

## Known limitation of this phase's scope

These tests do not yet cover: what happens if the account ID given turns out
to be invalid in format, or not found by the lookup API (both are Phase 2
concerns), or multi-turn greeting scenarios. Phase 2's test file will build
on the state this phase leaves the agent in (`stage: "await_account_id"`,
`account_id: null`) and take it from there.

## Sign-off

Phase 1 is **verified and ready**. Proceeding to Phase 2 (account lookup via
the `lookup-account` API).
