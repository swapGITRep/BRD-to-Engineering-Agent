# Business Requirements Document — Bank Statement Auto-Reconciliation Assistant

## 1. Overview

The Treasury Operations team manually reconciles daily bank statement line
items against the internal AP/AR ledger. A meaningful share of statement
lines arrive with no usable reference number — either the bank feed
truncates it, or the statement is a scanned PDF whose OCR extraction garbles
it — forcing an analyst to look the transaction up by hand. This BRD covers
a tool that ingests daily bank statements, matches each line to a ledger
entry, and surfaces low-confidence or unmatched lines for analyst review.

Project sponsor: Treasury Operations Lead. Target go-live: end of Q2.

## 2. Goals

- Reduce daily reconciliation effort from 3 analyst-hours to under 45 minutes.
- Auto-match at least 90% of statement lines with a clean reference number,
  and at least 60% of those without one.
- Surface every discrepancy the same business day it appears on the statement.

## 3. Functional Requirements

3.1 The system must ingest daily bank statements in CSV, OFX, and scanned
    PDF format (OCR text already extracted by an upstream service).

3.2 The system must normalize every statement line into a common schema:
    date, amount, payee, reference, memo.

3.3 The system must match a statement line to a ledger entry by reference
    number when one is present and well-formed.

3.4 The system must support fuzzy matching when the reference is missing or
    unreliable (e.g. OCR-garbled), using amount + a configurable date window
    + payee-name similarity, the same class of problem as any settlement or
    remittance reconciliation that can't rely on a clean reference number.

3.5 The system must assign every fuzzy match a confidence score and route
    anything below a configurable threshold to analyst review instead of
    auto-confirming it.

3.6 The system must let an analyst confirm, reject, or manually re-match a
    flagged line, capturing a reason code and free-text note.

3.7 The system must produce a daily reconciliation summary with an audit
    trail of every match decision, automatic or analyst-confirmed.

## 4. Non-Functional Requirements

4.1 A daily statement batch (up to 20,000 lines across all accounts) must
    complete matching within 15 minutes.

4.2 All statement and ledger data must be encrypted at rest and in transit.

4.3 The platform must retain reconciliation records for 7 years for audit.

4.4 Fuzzy-match confidence scoring must be explainable — an analyst
    reviewing a flagged line must be able to see which factors (amount,
    date proximity, name similarity) drove the score.

## 5. Constraints and Assumptions

- OCR extraction itself is out of scope; scanned statements arrive as
  already-extracted text from an existing upstream OCR service.
- The internal ledger is available via a read replica; no direct writes to
  the ledger from this tool.
- The team has prior experience with the organization's existing payments
  reconciliation platform and expects to reuse proven matching approaches
  where applicable, not invent a new technique from scratch.

## 6. Out of Scope

- The OCR engine and scanned-document pipeline upstream of this tool.
- Automated posting of confirmed matches back to the ledger.
- Multi-currency statements (all accounts in this phase are single-currency).

## 7. Success Metrics

- 90%+ auto-match rate for lines with a clean reference number.
- 60%+ auto-match rate for lines without one, at the configured confidence
  threshold.
- Mean time to surface a discrepancy under 1 business day.
- Zero audit findings related to reconciliation traceability.
