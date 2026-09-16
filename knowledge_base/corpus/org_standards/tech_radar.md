# Organization Tech Radar

Status values: ADOPT (default choice), TRIAL (use with a senior owner), HOLD
(do not start new work), RETIRE (migrate away).

## Languages & Runtimes

- Python 3.11+ — ADOPT for data, batch, ML, internal tooling.
- TypeScript / Node 20 — ADOPT for web frontends and BFFs.
- Go — TRIAL for high-throughput services with a senior owner.
- Java / Spring — HOLD (existing systems only; no new services).

## Web / Frontend

- React 18 + Vite + TypeScript — ADOPT.
- Next.js — ADOPT when SSR/SEO is required.
- Server-rendered Django templates — HOLD.
- Internal design system `@org/ds` — ADOPT; do not fork Material UI.

## Backend / Services

- FastAPI — ADOPT for Python services.
- Express / Fastify — ADOPT for Node services.
- gRPC — TRIAL for internal service-to-service.

## Data

- PostgreSQL (Azure Database for PostgreSQL Flexible Server) — ADOPT default OLTP.
- Azure Blob Storage — ADOPT for files and immutable landing zones.
- Redis (Azure Cache for Redis) — ADOPT for caching and queues at small scale.
- Azure Service Bus — ADOPT for durable messaging.
- Apache Spark / Databricks — TRIAL; only when data volume exceeds single-node
  processing. Prefer plain Python + Postgres for < 10M rows per batch.
- Snowflake — ADOPT for analytics warehouse.

## Platform

- Azure Container Apps — ADOPT default compute for services and web apps.
- Azure Kubernetes Service — HOLD unless a platform team owns the cluster.
- Azure Functions — ADOPT for event/timer glue, not for stateful apps.
- GitHub Actions — ADOPT for CI/CD, OIDC to Azure, no stored cloud secrets.
- Terraform or Bicep — ADOPT for infra as code.

## Identity & Security

- Okta / OIDC — ADOPT for workforce and B2B SSO.
- Azure Key Vault — ADOPT for secrets; no secrets in env files in production.
- Managed identities — ADOPT; avoid service-principal client secrets.
