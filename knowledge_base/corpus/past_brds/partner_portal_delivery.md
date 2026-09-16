# Past Delivery — Partner Self-Service Portal

## BRD summary

Replace a set of emailed spreadsheets with a portal where partners view orders,
download statements, and raise disputes. ~5,000 partner users, peak ~200
concurrent. SSO via partner IdPs (OIDC). WCAG 2.1 AA. Integrate with the order
service (REST, owned by another team) and the document store.

## What we built

- React 18 + Vite SPA using the org design system, deployed to Container Apps.
- A BFF (FastAPI) aggregating the order service and document store, handling
  OIDC and shaping responses for the UI.
- Dispute workflow persisted in PostgreSQL with an audit trail.
- No changes to the order service (out of scope, honored).

## Plan shape (actual)

Discovery & Design incl. design-system spike (3 wks) → Walking skeleton: auth +
one real screen end to end (3 wks) → Core screens: orders, statements, disputes
(6 wks) → Admin: user management, roles (2 wks) → Hardening: accessibility audit,
load test to 200 concurrent, pen test (3 wks) → Launch: pilot with 5 partners,
then GA (2 wks). Team: 5 engineers (4 FE-leaning, 1 BFF) + 1 EM. 19 weeks.

## Lessons

- Design tokens arrived in week 3, not week 2 — the skeleton used placeholders
  and reskinned later. Plan for design to be on the critical path or decouple it.
- OIDC with three partner IdPs each behaved slightly differently; budget 2 weeks
  not 1 for multi-IdP SSO.
- The team was new to accessibility; the audit found 40 issues. Bake axe checks
  into CI from day one and do a mid-build mini-audit.
