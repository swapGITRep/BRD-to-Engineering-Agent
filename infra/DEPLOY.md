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

```bash
az deployment group create -g $RG -n brd -f infra/main.bicep \
  -p namePrefix=$PREFIX \
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

## Secrets: provide them once, not on every deploy

The Bicep writes a Key Vault secret **only when you pass its parameter**.

| Situation | `openAiApiKey` / `langchainApiKey` |
|---|---|
| First deployment (new / empty vault) | **required** — pass real values (use `langchainApiKey='not-set'` to run without LangSmith) |
| Any later `az deployment group create` (infra change, add a param, etc.) | **omit them** — the values already in the vault are left untouched |
| Rotate / fix a key | don't redeploy — see below |

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

## Notes

- **Always-on**: `minReplicas = maxReplicas = 1`. Streamlit session state and the
  SQLite checkpointer are single-instance — don't scale out without Tier 2
  (Postgres + Azure AI Search). For a personal instance you can set
  `-p minReplicas=0` (cold starts, session loss) to cut cost to near zero.
- **LangSmith**: omit `langchainApiKey` to run without tracing (the `not-set`
  placeholder is treated as disabled).
- **Access control**: add Azure AD "Easy Auth" — `az containerapp auth`.
- **Custom domain**: `az containerapp hostname add` + free managed certificate.
