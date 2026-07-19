# Sample Conversations

**How these were produced:** every transcript below is the *actual, verbatim
output* of a real `python eval/eval_harness.py` run against the real
`gpt-4.1-nano` model and the real sandbox payment API — nothing here is
hand-typed, paraphrased, or simulated. All 4 scenarios passed on this run
(4/4). Note: the default model has since been upgraded to `gpt-4.1-mini`
(see `DESIGN.md` §4.8) after live testing found `nano` extraction
inconsistencies elsewhere in the flow — none of that affects the
correctness of the transcripts below, but a fresh run today would use the
newer default. See `eval/EVALUATION.md` for the full evaluation approach and
the timeline of how the project got to this point (it went through two LLM
provider swaps along the way — Claude → Gemini → OpenAI — each completed by
rewriting a single file, `payment_agent/extraction.py`, with zero changes
anywhere else, which is the LLM-isolation architecture described in
`DESIGN.md` working as intended).

---

## Sample 1: Successful end-to-end payment

```
User:  Hi
Agent: Hello! Please share your account ID to get started.

User:  yeah my account number is ACC1001 I think
Agent: Got it. Could you please confirm your full name, and either your date of birth, the last 4 digits of your Aadhaar, or your pincode?

User:  it's Nithin, Nithin Jain
Agent: Thanks. Could you verify your date of birth, Aadhaar last 4 digits, or pincode?

User:  I was born on 14th May 1990
Agent: Identity verified. Your outstanding balance is ₹1,250.75. How much would you like to pay?

User:  can I do 500 for now?
Agent: Great. Could you share your card number, CVV, expiry date?

User:  the card number is 4532 0151 1283 0366, expires December 2027, CVV is one two three
Agent: Payment successful! ₹500.00 was charged to your card ending in 0366. Your transaction ID is txn_1784440043873_qzh87p9.

Recap: hi Nithin Jain, we verified your identity and processed a payment of ₹500.00 successfully (transaction ID txn_1784440043873_qzh87p9). Thanks, and have a great day!
```

Every piece of messy phrasing here was extracted correctly on the first try:
the hedged account ID ("I think"), the repeated-name intro ("it's Nithin,
Nithin Jain"), the worded date, the partial-payment phrasing, and the
spaced-out card number with a worded expiry and spelled-out CVV digits, all
combined in one final message.

---

## Sample 2: Verification failure (user exhausts retries)

```
User:  Hi
Agent: Hello! Please share your account ID to get started.

User:  account id: acc1002
Agent: Got it. Could you please confirm your full name, and either your date of birth, the last 4 digits of your Aadhaar, or your pincode?

User:  my name is Rajarajeswari Balasubramaniam, DOB 1990-01-01
Agent: That doesn't match our records. Please double-check and provide your full name along with your date of birth, Aadhaar last 4 digits, or pincode. (2 of 3 attempts remaining)

User:  my name is Rajarajeswari Balasubramaniam, pincode 111111
Agent: That doesn't match our records. Please double-check and provide your full name along with your date of birth, Aadhaar last 4 digits, or pincode. (1 of 3 attempts remaining)

User:  my name is Rajarajeswari Balasubramaniam, Aadhaar last four 0000
Agent: I wasn't able to verify your identity after several attempts, so for your security I have to close this session here. Please contact support if you'd like to try again.
```

The name is correct on every attempt and only the secondary factor is
wrong — deliberately isolating that a single wrong field fails the whole
claim, per the strict "name AND a secondary factor" rule (DESIGN.md §4.2).
Once closed, a further message gets a fixed reply and the agent does not
re-engage the LLM at all (`agent.state.closed`, `nlg.closed_message()`).

---

## Sample 3: Payment failure (expired card), corrected on retry — also the ACC1004 leap-year DOB edge case

```
User:  Hi
Agent: Hello! Please share your account ID to get started.

User:  ACC1004
Agent: Got it. Could you please confirm your full name, and either your date of birth, the last 4 digits of your Aadhaar, or your pincode?

User:  Rahul Mehta
Agent: Thanks. Could you verify your date of birth, Aadhaar last 4 digits, or pincode?

User:  DOB is 1988-02-29
Agent: Identity verified. Your outstanding balance is ₹3,200.50. How much would you like to pay?

User:  pay 1000
Agent: Great. Could you share your card number, CVV, expiry date?

User:  card 4111111111111111, cvv 123, expiry 01/2020
Agent: That expiry date looks invalid or already expired. Could you re-enter it? (2 of 3 attempts remaining)

User:  sorry, the expiry is actually 01/2030
Agent: Payment successful! ₹1,000.00 was charged to your card ending in 1111. Your transaction ID is txn_1784440059186_25u0yxz.

Recap: hi Rahul Mehta, we verified your identity and processed a payment of ₹1,000.00 successfully (transaction ID txn_1784440059186_25u0yxz). Thanks, and have a great day!
```

`1988-02-29` is accepted as a real date (1988 is a leap year) and verifies
successfully on the first attempt. The expired card (`01/2020`) is caught by
client-side validation before any API call and counted against the shared
payment-retry limit; supplying only the corrected expiry (keeping the same
card number and CVV already on file) completes the payment.

---

## Sample 4: Edge case — rhetorical aside embedded in the answer, plus "full amount" phrasing

```
User:  Hi
Agent: Hello! Please share your account ID to get started.

User:  acc 1002
Agent: Got it. Could you please confirm your full name, and either your date of birth, the last 4 digits of your Aadhaar, or your pincode?

User:  Rajarajeswari Balasubramaniam
Agent: Thanks. Could you verify your date of birth, Aadhaar last 4 digits, or pincode?

User:  Aadhaar ends with 9876, shall I give pincode instead?
Agent: Identity verified. Your outstanding balance is ₹540.00. How much would you like to pay?

User:  just clear the full amount
Agent: Great. Could you share your card number, CVV, expiry date?

User:  card number 4532015112830366, expiry 12/27, cvv 123
Agent: Payment successful! ₹540.00 was charged to your card ending in 0366. Your transaction ID is txn_1784440067956_6z4r2do.

Recap: hi Rajarajeswari Balasubramaniam, we verified your identity and processed a payment of ₹540.00 successfully (transaction ID txn_1784440067956_6z4r2do). Thanks, and have a great day!
```

This message is taken verbatim from the assignment's own "what real users
sound like" examples: *"Aadhaar ends with 9876, shall I give pincode
instead?"* The extractor correctly pulled out `9876` as the Aadhaar value
despite the trailing rhetorical question, and "just clear the full amount"
resolved to the exact balance (₹540.00) — a `Decimal` from the lookup API,
not a number restated by the LLM.

---

## A fifth case worth knowing about: zero-balance accounts (ACC1003)

Not part of the live harness above, but covered by
`tests/test_fsm_scripted.py::test_zero_balance_account_closes_immediately_without_asking_for_payment`
and worth calling out: an account with nothing owed (₹0.00, like the
assignment's ACC1003) is recognized immediately after verification and the
conversation closes cleanly with no amount/card collection ever attempted —
`"Identity verified. Good news, Priya Agarwal -- your outstanding balance is
already ₹0.00, so there's nothing to pay right now."` This exists because an
earlier version of the code had a real bug here (see DESIGN.md §4.6): the
"pay the full amount" shortcut resolved directly to the balance and bypassed
the validator that rejects zero-amount payments, which would have let a
₹0.00 payment attempt reach the card-collection stage. The fix recognizes
the zero-balance case structurally, before that stage is ever entered,
rather than patching around it afterward.
