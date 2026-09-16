# Business Requirements Document — Regulated Customer Ledger Service

## 1. Overview

Compliance requires customer funds held on the platform to be tracked in a
dedicated, auditable ledger separate from the general application database,
ahead of the company's upcoming money-transmitter license renewal. This BRD
covers the ledger service that will be the system of record for customer
balances.

Sponsor: Chief Compliance Officer, co-sponsored by VP Engineering. Target:
must be live and audit-ready before the license renewal window in Q3.

## 2. Goals

- Provide a single, immutable system of record for every customer balance
  movement, acceptable to external auditors and regulators.
- Pass the upcoming money-transmitter license audit with zero material
  findings related to fund tracking.
- Reduce manual reconciliation currently performed by the Compliance team at
  month-end.

## 3. Functional Requirements

3.1 The system must record every balance-affecting event (deposit, withdrawal,
    fee, transfer, refund, chargeback) as an immutable, append-only ledger
    entry — no entry may be updated or deleted after it is written.

3.2 The system must compute a customer's current balance as the sum of their
    ledger entries, not as a separately-stored mutable value, to guarantee the
    balance is always reconstructable from history.

3.3 Every ledger entry must record its source event, timestamp, amount,
    currency, counterparty (where applicable), and the identity of the
    initiating actor (system process or authenticated staff member).

3.4 The system must support double-entry bookkeeping: every ledger entry that
    moves funds must have a matching offsetting entry, and the system must
    reject any write that would leave the books unbalanced.

3.5 The system must provide an internal audit interface allowing Compliance
    staff to view the full, unaltered history of any customer's balance.

3.6 The system must support a formal correction mechanism (a reversing entry
    plus a new corrected entry) for fixing errors — corrections must never
    overwrite or delete the original erroneous entry.

3.7 The system must generate the regulator-required daily trial balance
    report, showing the ledger is balanced across all customers.

3.8 The system must flag any ledger entry associated with a customer on the
    sanctions/watchlist for manual review before it is finalized.

## 4. Non-Functional Requirements

4.1 Every ledger entry and every access to ledger data must be logged in a
    tamper-evident audit trail retained for a minimum of 7 years, per
    money-transmitter recordkeeping requirements.

4.2 Ledger data at rest and in transit must be encrypted, and access must be
    restricted by role with all access attempts (successful and denied)
    logged.

4.3 The ledger must guarantee strong consistency for balance reads used in
    any funds-availability decision — an eventually-consistent read must never
    be used to authorize a withdrawal.

4.4 The system must be able to produce a full export of any customer's ledger
    history, in a regulator-specified format, within 24 hours of a request.

4.5 The double-entry balance check in 3.4 must be enforced atomically; no
    partially-written, unbalanced transaction may ever be visible to readers.

4.6 The system must support data residency requirements — customer ledger
    data for EU customers must remain stored within the EU.

## 5. Constraints and Assumptions

- The existing application database is not itself audit-grade and cannot be
  repurposed as the ledger; this must be a distinct system of record.
- The compliance and audit requirements in this BRD come from external legal
  counsel's review of money-transmitter regulations and are not negotiable
  on scope, only on delivery sequencing.
- The team is 4 engineers, familiar with the company's existing Postgres +
  Azure stack; no prior experience building ledger/accounting systems.
- The license renewal date is fixed and cannot move.

## 6. Out of Scope

- Migrating historical balance data from before the ledger's go-live date
  (handled as a separate reconciliation project).
- Multi-currency FX conversion logic (ledger stores amounts in the currency
  they were recorded; conversion is out of scope).

## 7. Success Metrics

- Zero material audit findings related to fund tracking at the license
  renewal review.
- 100% of balance-affecting events represented as immutable ledger entries
  with no direct database mutation path remaining.
- Month-end manual reconciliation effort reduced to near zero.
