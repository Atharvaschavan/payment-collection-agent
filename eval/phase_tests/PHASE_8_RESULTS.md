# Phase 8 Test Results — Recap and Close the Conversation

**Assignment step covered:** Step 8 of 8 — *"Recap and close the
conversation."*

**Test file:** [`phase_8_recap_and_close.json`](./phase_8_recap_and_close.json)
**Runner:** [`../run_phase_test.py`](../run_phase_test.py)
**Run command:** `python eval/run_phase_test.py eval/phase_tests/phase_8_recap_and_close.json`

## Methodology

**Live** run: real OpenAI extraction and the real sandbox API for every
path that reaches one. This is the last phase, so it deliberately tests
across the *whole* flow rather than one stage in isolation: every one of
the system's five terminal paths (successful payment, user cancellation,
account-lookup exhaustion, identity-verification exhaustion, and
payment-attempt exhaustion) is driven to completion and then probed with
one more turn afterward.

**Scope note:** the recap *content* for a successful payment (transaction
ID + outcome present) was checked in Phase 6, and the zero-balance close
(`no_balance_due`) was checked in Phase 4. This phase adds two things not
yet covered by any prior phase: (1) that the recap sentence specifically
*binds* the correct name, amount, and transaction ID together — not just
that those facts appear somewhere in the reply — and (2) that closing is
actually permanent for every terminal path, not just the success path
tested in Phase 6.

## Result: 5/5 test cases passed — no new issues found

| # | Test ID | What it checks | Result |
|---|---|---|---|
| 1 | `recap_sentence_correctly_binds_name_amount_and_transaction_id_together` | The "Recap: hi Rahul Mehta..." sentence names the actual verified user and actual amount (₹1,500.00), not a generic template | ✅ PASS |
| 2 | `post_close_input_after_cancellation_gets_fixed_closing_reply` | After cancelling, even "let's continue, ACC1001" gets the fixed closed-conversation reply | ✅ PASS |
| 3 | `post_close_input_after_account_lookup_exhaustion_gets_fixed_closing_reply` | After lookup exhaustion, even a genuinely valid account ID (ACC1001) doesn't reopen the session | ✅ PASS |
| 4 | `post_close_input_after_verification_exhaustion_gets_fixed_closing_reply` | After verification exhaustion, even the *correct* identity doesn't reopen the session or verify retroactively | ✅ PASS |
| 5 | `post_close_input_after_payment_attempts_exhaustion_gets_fixed_closing_reply` | After payment-attempt exhaustion, even fully valid card details don't trigger a payment | ✅ PASS |

No real issues were found or fixed during this phase. The single
short-circuit at the top of `PaymentCollectionAgent.next()`:

```python
if self.state.closed:
    return {"message": nlg.closed_message()}
```

is unconditional and runs before the extractor is even called, so it
structurally cannot depend on *which* path led to closure — there's no way
for one terminal path to be airtight while another leaks. Tests #3 and #4
are the more interesting checks here, since they specifically try to
"trick" the agent back open with input that would otherwise be perfectly
valid (a real account ID, the actual correct identity) — confirming the
guard is a hard gate on `state.closed`, not something that re-evaluates
whether the new input happens to be good enough to proceed.

## What this confirms

- **Closing is genuinely terminal**, across all five ways a conversation
  can end, not just the success path. No amount of correct or well-formed
  follow-up input reopens a closed session.
- **No API or LLM call happens after close** — the guard returns before
  `self.extractor.extract(...)` is ever invoked, so a closed conversation
  can't accidentally trigger a duplicate lookup or payment call, and can't
  burn API quota on input that will be discarded anyway.
- **The recap is a faithful summary, not a template with the right facts
  floating nearby** — the specific sentence structure ties name, amount,
  and transaction ID together correctly for a real live API response.

## Sign-off

Phase 8 is **verified and ready**, with no issues found. This completes
live phase-by-phase verification of all 8 steps in the assignment's
problem statement.

**Full live tally across all 8 phases:**

| Phase | Cases | Result |
|---|---|---|
| 1 — Greet & prompt for account ID | 9 | ✅ 9/9 |
| 2 — Look up account via API | 9 | ✅ 9/9 |
| 3 — Identity verification | 14 | ✅ 14/14 |
| 4 — Share outstanding balance | 6 | ✅ 6/6 |
| 5 — Collect amount & card details | 11 | ✅ 11/11 |
| 6 — Process the payment | 4 | ✅ 4/4 |
| 7 — Communicate the outcome | 4 | ✅ 4/4 |
| 8 — Recap and close | 5 | ✅ 5/5 |
| **Total** | **62** | **✅ 62/62** |

Combined with the 60-test offline unit/FSM suite (`tests/`, run via
`pytest`), the project has **122 passing tests** across both live and
offline layers, plus the direct-to-API contract verification that caught
the `invalid_args` sandbox quirk in Phase 6.
