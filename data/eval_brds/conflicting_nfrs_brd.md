# Business Requirements Document — Real-Time Fraud Scoring Gateway

## 1. Overview

The Risk team wants every checkout request scored for fraud in real time
before payment is authorized, using the existing ML fraud model. This BRD
describes a gateway service that sits in the checkout path.

Sponsor: Head of Risk. Target go-live: next quarter.

## 2. Goals

- Block high-risk transactions before they are authorized, not after.
- Keep checkout feeling instant — conversion drops sharply with any added
  latency at checkout.
- Give the fraud model full context (device, session history, account age,
  order contents) so its score is trustworthy.

## 3. Functional Requirements

3.1 The system must score every checkout request using the existing fraud
    model before payment authorization proceeds.

3.2 The fraud model must be called synchronously in the checkout request path,
    using the full feature set the model was trained on (device fingerprint,
    30-day session history, account age, order line items).

3.3 The system must block or step-up (require additional verification)
    transactions scoring above the configured risk threshold.

3.4 The system must log every score, the features used, and the resulting
    decision for later audit and model retraining.

3.5 Risk analysts must be able to review and override a block decision within
    the same business day.

3.6 The system must NOT introduce any additional customer-facing step (no new
    CAPTCHA, no new confirmation screen) for transactions below the risk
    threshold — the checkout flow must feel identical to today for good actors.

## 4. Non-Functional Requirements

4.1 The end-to-end checkout request, including the fraud score, must return in
    under 150ms at p99 — this is a hard constraint from the checkout team, who
    have measured a 7% conversion drop for every 100ms added at this step.

4.2 The full feature set in 3.2 (30-day session history, device fingerprint
    lookup, account age) must be retrieved fresh for every request — cached or
    stale features are not acceptable per the Risk team's model validation.

4.3 The gateway must be available 99.95% of the time; if the fraud service is
    unavailable, checkout must still complete (fail open), but every fail-open
    transaction must be flagged for next-day review.

4.4 All scoring decisions and the features used must be retained for 2 years
    for regulatory and model-audit purposes.

4.5 The system must re-authenticate the customer's session before any override
    action in 3.5 is applied, per the existing step-up auth policy.

## 5. Constraints and Assumptions

- The existing fraud model is a synchronous REST endpoint with a measured
  p99 latency of 180-220ms on its own, before any feature retrieval.
- Session history and device fingerprint lookups currently live in two
  separate services, each with their own latency profile.
- The team is 5 engineers, strong in Go and Kafka, with production ML-serving
  experience limited to batch scoring so far.

## 6. Out of Scope

- Retraining or changing the fraud model itself.
- Fraud scoring for non-checkout flows (account creation, password reset).

## 7. Success Metrics

- Checkout p99 latency stays under 150ms after the gateway is introduced.
- Fraud model uses its full, freshly-retrieved feature set on every scored
  transaction.
- No measurable increase in false declines for legitimate customers.
