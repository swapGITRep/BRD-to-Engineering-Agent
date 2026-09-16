# Past Delivery — Legacy Billing Export Replacement

## BRD summary

Finance needed a replacement for a nightly Access-database export that produced
revenue reports for the accounting close. Volume ~2M invoice lines/night. Hard
requirement: report available by 06:00, seven years retention, full audit of any
manual adjustment.

## What we built

- Immutable landing zone in Blob for the source extract.
- Python normalization job (no Spark — volume well within single-node).
- PostgreSQL for the canonical model and adjustment ledger (append-only).
- A small FastAPI service for analysts to view and annotate adjustments.
- Nightly report generation to Blob + a Power BI dataset refresh.
- Deployed on Azure Container Apps; scheduled via an Azure Functions timer.

## Plan shape (actual)

Discovery & Design (2 wks) → Walking skeleton: landing → normalize → Postgres
(3 wks) → Report generation + audit ledger (4 wks) → Analyst UI (3 wks) →
Hardening: perf test at 2M lines, retention lifecycle, threat model (3 wks) →
Launch & parallel run against the legacy export (2 wks). Team: 3 engineers +
0.5 EM. Total 17 weeks against a 20-week BRD target.

## What went wrong / lessons

- The source extract schema was undocumented; discovery took a week longer than
  planned. Now we always add a discovery-tax multiplier to file integrations.
- First perf test at full volume failed the 06:00 SLA; fixed with batched
  upserts and one index. Hardening should always include a full-volume run.
- Parallel run for two closes caught three edge cases the tests missed. Keep it.
