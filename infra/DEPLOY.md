# Tier 1 deployment — Azure Container Apps

Single always-on Container App + Azure Files (persistent RAG index / output) +
Key Vault. The SQLite checkpoint DB lives on local container disk, not Azure
Files (SQLite locking is unreliable over SMB). A new deployment also creates Log Analytics, Application
Insights, a Container Apps environment and an ACR; reusing an existing
environment/ACR skips those.

## Prerequisites

- Azure CLI (`az`) logged in: `az login`
- An OpenAI API key; optionally a LangSmith key
- Resource providers registered (once per subscription):
  ```bash
  az provider register --namespace Microsoft.App
  az provider register --namespace Microsoft.OperationalInsights
  az provider register --namespace Microsoft.ContainerRegistry
  az provider register --namespace Microsoft.KeyVault
  az provider register --namespace Microsoft.Insights
  ```

## Option A — plain `az` CLI

```bash
RG=rg-brd-agent            # resource group that will hold the app
LOC=centralindia
PREFIX=brdagent

az group create -n $RG -l $LOC   # skip if the RG already exists
```

### 1a. Fresh deployment (creates env + ACR + monitoring)

```bash
az deployment group create -g $RG -n brd -f infra/main.bicep \
  -p namePrefix=$PREFIX \
     openAiApiKey='sk-...' \
     langchainApiKey='lsv2_...'
```

### 1b. …or reuse an existing environment / ACR

The existing resources must be in **this resource group** and the same region.
When an environment is reused, the template does **not** create Log Analytics or
App Insights — pass an existing connection string if you want telemetry.

On a **redeploy of an app that already has a real image running**, also pass
`containerImage` — see "Always pass `containerImage` on a redeploy" below for
why omitting it is a live-caught way to accidentally revert to a placeholder
image.

```bash
az deployment group create -g $RG -n brd -f infra/main.bicep \
  -p namePrefix=$PREFIX \
     containerImage='<acrLoginServer>/brd-agent:<the tag currently running>' \
     existingEnvironmentName='cae-saathiapp-dev' \
     existingAcrName='<your-acr-name>' \
     appInsightsConnectionString='InstrumentationKey=...;IngestionEndpoint=...' \
     openAiApiKey='sk-...' \
     langchainApiKey='lsv2_...'
```

The two Azure Files links added to the shared environment are name-prefixed
(`brdagent-vectorstore`, `brdagent-output`) so they never collide with links
other apps put on the same environment. The LangGraph checkpoint DB
(`CHECKPOINT_DB`) is deliberately **not** on Azure Files — SQLite's file
locking is unreliable over SMB and causes intermittent `database is locked`
errors — so it lives on the container's own local disk instead. That means
checkpoint history doesn't survive a restart/redeploy, which is fine: the web
UI never resumes a run across restarts, and Run History reads the `output`
share, not the checkpoint DB.

### 2. Read the outputs

```bash
ACR=$(az deployment group show -g $RG -n brd --query properties.outputs.acrName.value -o tsv)
APP=$(az deployment group show -g $RG -n brd --query properties.outputs.appName.value -o tsv)
LOGIN=$(az deployment group show -g $RG -n brd --query properties.outputs.acrLoginServer.value -o tsv)
URL=$(az deployment group show -g $RG -n brd --query properties.outputs.appUrl.value -o tsv)
```

### 3. Build the real image and roll it out

```bash
az acr build -r $ACR -t brd-agent:v1 .
az containerapp update -g $RG -n $APP --image "$LOGIN/brd-agent:v1"
echo "App: $URL"
```

First boot builds the RAG index onto the `vectorstore` file share (~1 min);
later restarts skip it.

### Update after a code change

```bash
az acr build -r $ACR -t brd-agent:v2 .
az containerapp update -g $RG -n $APP --image "$LOGIN/brd-agent:v2"
```

Each update creates a new revision; roll back with
`az containerapp revision list -g $RG -n $APP` then `... revision activate`.

## Always pass `containerImage` on a redeploy of an existing app

`containerImage`'s default (`mcr.microsoft.com/k8se/quickstart:latest`) exists
only for the very first deployment, before any real image has been built —
its own `@description` says so. Live-caught: running `az deployment group
create` against an **existing** deployment without passing `containerImage`
silently reverts the running app to that placeholder image, and sets
`APP_BUILD` to `latest` (`imageTag = last(split(containerImage, ':'))`
resolves to `latest` from the default). Always pass the image that's actually
running:

```bash
IMAGE=$(az containerapp show -g $RG -n $APP --query "properties.template.containers[0].image" -o tsv)
az deployment group create -g $RG -n brd -f infra/main.bicep \
  -p containerImage="$IMAGE" \
     existingEnvironmentName='cae-saathiapp-dev' \
     existingAcrName='<your-acr-name>' \
     keyVaultName='<your-key-vault-name>'
```

## Recovering from a revision that fails to activate

Live-caught: a full `az deployment group create` against this app produced a
revision that never passed its Liveness/Readiness probes and was eventually
marked `ActivationFailed` (`"Deployment Progress Deadline Exceeded. 0/1
replicas ready."`) — twice, even after loosening the probe timing. A plain
`az containerapp update --image <the currently running image>` (no bicep, no
template changes) against the *same* now-updated app resource booted
healthy in under a minute. Best-supported explanation: the full template
reconciliation re-touches resources (role assignments, Key Vault access)
even when their values are unchanged, and a replica created immediately
after can get caught in a brief propagation window resolving its
secrets/mounts — a revision created moments later, from the already-settled
template, doesn't hit it.

If `az deployment group create` reports success but the resulting revision
shows `ActivationFailed` (`az containerapp revision show -g $RG -n $APP
--revision <name> --query properties.runningStateDetails`):

```bash
IMAGE=$(az containerapp show -g $RG -n $APP --query "properties.template.containers[0].image" -o tsv)
az containerapp update -g $RG -n $APP --image "$IMAGE" --set-env-vars "APP_BUILD=$(echo $IMAGE | cut -d: -f2)"
```

Don't skip `--set-env-vars APP_BUILD=...` here — `az containerapp update
--image` only ever updates the image, never other env vars, so `APP_BUILD`
stays whatever the failed bicep deployment last set it to (`latest`, per the
gotcha above) unless set explicitly in the same command. This is the same
one-line fix `.github/workflows/deploy.yml`'s `build-and-deploy` job already
applies on every CI deploy — see `TECHNICAL_DESIGN.md` §11 for the earlier
incident that introduced it there.

Throughout all of this the app stays up: Container Apps keeps serving
traffic from the last healthy revision automatically while a new one fails
to activate, so there is no user-facing downtime to race against while
diagnosing.

## Log tables: dedicated only

Every environment routes logs through `appLogsConfiguration.destination:
'azure-monitor'` plus a diagnostic setting for `ContainerAppConsoleLogs`,
`ContainerAppSystemLogs` and `ContainerAppHTTPLogs`. These are dedicated
(resource-specific) tables with clean column names. A **fresh** deployment gets
this from `infra/main.bicep` (`container-app-logs` setting). The legacy
`log-analytics` destination, which wrote `ContainerAppConsoleLogs_CL` /
`ContainerAppSystemLogs_CL` (columns suffixed `_s`), is no longer used.

An **existing** environment is not managed by this Bicep. `cae-saathiapp-dev`
was migrated by hand on 2026-09-24; to migrate another one:

```bash
ENVID=$(az containerapp env show -g $RG -n <env> --query id -o tsv)
WS=$(az monitor log-analytics workspace show -g $RG -n <workspace> --query id -o tsv)

# 1. Diagnostic setting with all three categories (a category can't be in two
#    settings, so reuse the name of any existing one to overwrite it).
az monitor diagnostic-settings create --name container-app-logs --resource "$ENVID" \
  --workspace "$WS" --export-to-resource-specific true \
  --logs '[{"category":"ContainerAppConsoleLogs","enabled":true},
           {"category":"ContainerAppSystemLogs","enabled":true},
           {"category":"ContainerAppHTTPLogs","enabled":true}]'

# 2. The cut-over. Legacy _CL writes stop; dedicated tables start.
az containerapp env update -g $RG -n <env> --logs-destination azure-monitor
```

Live-observed on `cae-saathiapp-dev`:

- **No dual-write.** With the destination still `log-analytics`, enabling the
  Console/System categories produced zero dedicated-table rows after 16+
  minutes. Only the destination change starts them.
- **Cut-over cost.** First Console/System rows arrived ~10-12 minutes after the
  flip, so expect that gap. The flip did not restart the app (same revision,
  still `Healthy`). Other apps sharing the environment are affected too.
- **Old tables can't be deleted.** `ContainerAppConsoleLogs_CL` /
  `ContainerAppSystemLogs_CL` are platform-created classic tables. Delete,
  retention-update and `table migrate` all fail (`Changing Classic table ...
  schema ... is forbidden`; migrate fails on the `_timestamp_d` column). They
  now receive nothing and their data expires with workspace retention.
- **Rollback:** `az containerapp env update ... --logs-destination
  log-analytics --logs-workspace-id <customerId> --logs-workspace-key <key>`
  (get the key with `az monitor log-analytics workspace get-shared-keys`; don't
  paste it anywhere that is logged).

Query rewrite: drop the `_CL` suffix and the `_s` column suffix
(`ContainerAppName_s` -> `ContainerAppName`, `Log_s` -> `Log`,
`RevisionName_s` -> `RevisionName`, `Reason_s` -> `Reason`, `EventSource_s` ->
`EventSource`). `Type_s` (`Normal`/`Warning`) has **no equivalent** —
`ContainerAppSystemLogs.Type` is just the table name — so classify events by
`Reason` (e.g. `ProbeFailed`, `ContainerTerminated`) instead.

## Secrets: provide them once, not on every deploy

The Bicep writes a Key Vault secret **only when you pass its parameter**.

| Situation | `openAiApiKey` / `langchainApiKey` / `jiraApiToken` |
|---|---|
| First deployment (new / empty vault) | `openAiApiKey` **required**; `langchainApiKey` and `jiraApiToken` also need *some* value the first time each param is introduced (use `'not-set'` to run without that feature) — the Container App's secret reference must resolve to a real Key Vault entry, even a placeholder one |
| Any later `az deployment group create` (infra change, add a param, etc.) | **omit them** — the values already in the vault are left untouched |
| Rotate / fix a key | don't redeploy — see below |

`jiraSiteUrl` / `jiraEmail` / `jiraProject` are plain (non-secret) params —
pass them whenever they change; omitting them redeploys with their bicep
defaults, not with whatever the running app currently has.

### Rotate or fix a key (no redeploy)

```bash
KV=$(az deployment group show -g $RG -n brd --query properties.outputs.keyVaultName.value -o tsv)
az keyvault secret set --vault-name $KV -n OPENAI-API-KEY --value 'sk-new'
az containerapp revision restart -g $RG -n $APP \
  --revision $(az containerapp show -g $RG -n $APP --query properties.latestRevisionName -o tsv)
```

(Your own account needs `Key Vault Secrets Officer` on the vault to run
`secret set` — the Bicep grants access only to the app's managed identity.)

### Ship a new image (no redeploy)

```bash
docker buildx build --platform linux/amd64 -t <acrLoginServer>/brd-agent:vN --push .
az containerapp update -g $RG -n $APP --image <acrLoginServer>/brd-agent:vN
```

## Option B — `azd` (one command)

```bash
azd auth login
azd env new brdagent
azd env set OPENAI_API_KEY 'sk-...'
azd env set LANGCHAIN_API_KEY 'lsv2_...'
# to reuse existing infra:
azd env set EXISTING_CONTAINER_APPS_ENV 'cae-saathiapp-dev'
azd env set EXISTING_ACR_NAME '<your-acr-name>'
azd up
```

## What gets created

| Resource | Name | Created when |
|---|---|---|
| Container App | `ca-<prefix>` | always |
| Managed identity | `id-<prefix>` | always — gets `AcrPull` + `Key Vault Secrets User` |
| Key Vault | `kv-<prefix>-<hash>` | always — holds `OPENAI-API-KEY`, `LANGCHAIN-API-KEY` (RBAC) |
| Storage Account | `st<prefix><hash>` | always — 2 Azure Files shares mounted at `/app/{vectorstore,output}` (checkpoints DB is local disk) |
| Env storage links | `<prefix>-{vectorstore,checkpoints,output}` | always (on the new or existing env) |
| Container Apps env | `cae-<prefix>` | only if `existingEnvironmentName` is blank |
| Container Registry | `acr<prefix><hash>` | only if `existingAcrName` is blank |
| Log Analytics + App Insights | `law-<prefix>`, `ai-<prefix>` | only if `existingEnvironmentName` is blank |
| Diagnostic setting | `container-app-logs` (console, system, HTTP -> dedicated tables) | only if `existingEnvironmentName` is blank |

## Notes

- **Always-on**: `minReplicas = maxReplicas = 1`. Streamlit session state and the
  SQLite checkpointer are single-instance — don't scale out without Tier 2
  (Postgres + Azure AI Search). For a personal instance you can set
  `-p minReplicas=0` (cold starts, session loss) to cut cost to near zero.
- **LangSmith**: omit `langchainApiKey` to run without tracing (the `not-set`
  placeholder is treated as disabled).
- **Jira ticket check**: optional — the PoC Planner's `check_related_jira_tickets`
  tool degrades to "not configured, use judgment" rather than failing the run
  if `jiraApiToken`/`jiraSiteUrl`/`jiraEmail` aren't set. See `.env.example`
  for the local-dev equivalent.
- **Access control**: add Azure AD "Easy Auth" — `az containerapp auth`.
- **Custom domain**: `az containerapp hostname add` + free managed certificate.
