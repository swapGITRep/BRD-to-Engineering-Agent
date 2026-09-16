# Security Baseline

Non-negotiable controls for every new system. The architecture must show how
each applies or why it does not.

## Identity & Access

- Authenticate via Okta / OIDC. No bespoke password stores for workforce users.
- Authorize with role-based access; least privilege by default.
- Sensitive or irreversible actions (write-offs, deletions, config changes) are
  restricted by role AND logged to the audit trail with actor and reason.
- Service-to-service auth uses managed identities or short-lived tokens.

## Data Protection

- Encrypt in transit (TLS 1.2+) and at rest (platform-managed keys minimum).
- Classify data (public / internal / confidential / regulated) and handle per class.
- No confidential or regulated data in logs, URLs, or analytics events.
- Secrets live in Azure Key Vault, referenced by managed identity — never in
  source, container images, or plaintext env in production.

## Application Security

- Validate and encode all external input. Parameterized queries only.
- Dependency scanning and container image scanning in CI; block on criticals.
- SAST on pull requests. One threat-model review before the hardening phase.

## Operations

- Audit logs are append-only and retained per the compliance requirement.
- Alert on auth failures, privilege changes, and anomalous export volume.
- Documented incident response and a tested backup/restore path.
