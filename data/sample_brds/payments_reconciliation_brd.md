# Business Requirements Document — Payments Reconciliation Platform

## 1. Overview

The Finance Operations team currently reconciles payment settlements from four
payment service providers (PSPs) manually in spreadsheets. This BRD describes a
platform that ingests PSP settlement files, matches them against internal ledger
entries, and surfaces exceptions for analyst review.

Project sponsor: VP Finance Operations. Target go-live: end of Q3.

## 2. Goals

- Reduce month-end reconciliation effort from 6 analyst-days to under 1 analyst-day.
- Detect settlement discrepancies within 24 hours of the PSP file landing.
- Provide an auditable trail for every match and write-off decision.

## 3. Functional Requirements

3.1 The system must ingest settlement files from Stripe, Adyen, PayPal, and
    Braintree in their native formats (CSV and JSON).

3.2 The system must normalize each PSP file into a common settlement schema.

3.3 The system must match settlement lines to internal ledger transactions using
    transaction reference, amount, and currency.

3.4 The system should support fuzzy matching when the transaction reference is
    missing, using amount + date window + merchant account.

3.5 The system must let an analyst approve, reject, or write off an unmatched item,
    capturing a reason code and free-text note.

3.6 The system must produce a daily reconciliation summary report per PSP.

3.7 Analysts should be able to re-run matching for a given date range after a
    ledger correction.

## 4. Non-Functional Requirements

4.1 A daily settlement batch (up to 500,000 lines) must complete matching within
    30 minutes.

4.2 All settlement data must be encrypted at rest and in transit.

4.3 The platform must retain reconciliation records for 7 years for audit.

4.4 The system must be available 99.5% during business hours (07:00–19:00 UK).

4.5 Access to write-off actions must be restricted by role and logged.

## 5. Constraints and Assumptions

- Internal ledger data is available via a read replica; no direct writes to the ledger.
- PSP files arrive in an SFTP dropbox by 02:00 UK daily.
- The team is a 4-engineer squad familiar with Python and AWS; limited Spark experience.
- Must integrate with the existing Okta SSO.

## 6. Out of Scope

- Automated posting of write-offs back to the general ledger.
- Real-time (intraday) settlement streaming.
- FX rate sourcing — the ledger already stores booked FX rates.

## 7. Success Metrics

- 95% of settlement lines auto-matched without analyst intervention.
- Mean time to detect a discrepancy < 24 hours.
- Zero audit findings related to reconciliation traceability.
