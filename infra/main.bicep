// ─────────────────────────────────────────────────────────────────────────────
// BRD Dev Agent — Tier 1 infrastructure (single always-on Container App).
//
// Provisions: Log Analytics + Application Insights, Azure Container Registry
// (Basic), a user-assigned managed identity, a Storage Account with two
// Azure Files shares (vector index / output), Key Vault (RBAC) with the two
// API-key secrets, a Container Apps environment, and the Container App
// itself. The LangGraph SQLite checkpoint DB deliberately stays on the
// container's own local disk, not Azure Files — see the `shares` comment
// below for why.
//
// Deploy (resource-group scope):
//   az group create -n rg-brd-agent -l centralindia
//   az deployment group create -g rg-brd-agent -f infra/main.bicep \
//     -p namePrefix=brdagent openAiApiKey=<sk-...> langchainApiKey=<lsv2-...>
//
// Then build & roll out the real image:
//   az acr build -r <acrName> -t brd-agent:v1 .
//   az containerapp update -g rg-brd-agent -n <appName> --image <acrLoginServer>/brd-agent:v1
// ─────────────────────────────────────────────────────────────────────────────

targetScope = 'resourceGroup'

@description('Short prefix for resource names (3-12 lowercase alphanumerics).')
@minLength(3)
@maxLength(12)
param namePrefix string = 'brdagent'

@description('Azure region. Defaults to the resource group location.')
param location string = resourceGroup().location

@description('Container image to deploy. Leave as the quickstart image for the first deployment, then update with your ACR image.')
param containerImage string = 'mcr.microsoft.com/k8se/quickstart:latest'

@description('Reuse an existing Container Apps environment (must be in THIS resource group and region). Leave blank to create a new one.')
param existingEnvironmentName string = ''

@description('Reuse an existing Azure Container Registry (in THIS resource group). Leave blank to create a new Basic registry.')
param existingAcrName string = ''

@description('Existing Application Insights connection string to send telemetry to. Only used when reusing an environment.')
param appInsightsConnectionString string = ''

@description('OpenAI API key. REQUIRED on the first deployment to a new/empty Key Vault; leave blank on redeploys and the existing secret value is kept.')
@secure()
param openAiApiKey string = ''

@description('LangSmith / LangChain API key. On a first deployment pass a value (use "not-set" to run without tracing); leave blank on redeploys to keep the existing value.')
@secure()
param langchainApiKey string = ''

@description('Jira API token for the PoC Planner ticket-check tool. Optional — on the first deployment that introduces this param, pass a value (use "not-set" to run without it); leave blank on redeploys to keep the existing value.')
@secure()
param jiraApiToken string = ''

@description('Jira site URL, e.g. https://yourcompany.atlassian.net. Not a secret.')
param jiraSiteUrl string = 'https://swapi4u.atlassian.net'

@description('Email address the Jira API token belongs to. Not a secret, but not public either — kept as a plain param rather than hardcoded.')
param jiraEmail string = 'swapi4u@gmail.com'

@description('Jira project name or key the ticket-check tool searches within. Blank = unscoped search.')
param jiraProject string = 'Agent Development Team'

@description('Key Vault name (globally unique, 3-24 chars). Blank = hashed default name.')
@maxLength(24)
param keyVaultName string = ''

param openAiModel string = 'gpt-4.1'
param openAiEmbedModel string = 'text-embedding-3-large'
param langchainTracing string = 'true'
param langchainProject string = 'brd-dev-agent'
param langchainEndpoint string = 'https://api.smith.langchain.com'

@description('Always-on: keep min = max = 1 for Tier 1 (Streamlit session state + SQLite checkpoints are single-instance).')
param minReplicas int = 1
param maxReplicas int = 1

@allowed(['0.25', '0.5', '0.75', '1.0'])
param cpu string = '0.5'
@allowed(['0.5Gi', '1.0Gi', '1.5Gi', '2.0Gi'])
param memory string = '1.0Gi'

// ── Names ────────────────────────────────────────────────────────────────────
var token = toLower(uniqueString(resourceGroup().id, namePrefix))
var acrName = take('acr${namePrefix}${token}', 50)
var storageName = take('st${namePrefix}${token}', 24)
var kvName = empty(keyVaultName) ? take('kv-${namePrefix}-${take(token, 6)}', 24) : keyVaultName
var lawName = 'law-${namePrefix}'
var aiName = 'ai-${namePrefix}'
var uamiName = 'id-${namePrefix}'
var envName = 'cae-${namePrefix}'
var appName = 'ca-${namePrefix}'
var imageTag = last(split(containerImage, ':'))

// SQLite's checkpoint DB is deliberately NOT on an Azure Files share: SQLite's
// file locking is unreliable over SMB (spurious "database is locked" even with
// a busy_timeout, since lock-release notifications don't propagate correctly
// over the network protocol). It lives on the container's own local disk
// instead — checkpoint history doesn't survive a restart, but nothing in this
// app relies on that (the web UI never resumes a thread across restarts; Run
// History reads the separate `output` share, not the checkpoint DB).
var shares = ['vectorstore', 'output']
var useExistingEnv = !empty(existingEnvironmentName)
var useExistingAcr = !empty(existingAcrName)
var envNameEffective = useExistingEnv ? existingEnvironmentName : envName

// Built-in role definition IDs
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var kvSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'

// ── Observability (only when creating a new environment) ─────────────────────
resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = if (!useExistingEnv) {
  name: lawName
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    workspaceCapping: { dailyQuotaGb: 1 }
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = if (!useExistingEnv) {
  name: aiName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: law.id
  }
}

#disable-next-line BCP318
var aiConnectionString = useExistingEnv ? appInsightsConnectionString : appInsights.properties.ConnectionString

// ── Identity ─────────────────────────────────────────────────────────────────
resource uami 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: uamiName
  location: location
}

// ── Container Registry ───────────────────────────────────────────────────────
resource newAcr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = if (!useExistingAcr) {
  name: acrName
  location: location
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: false
  }
}

resource existingAcr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' existing = if (useExistingAcr) {
  name: existingAcrName
}

#disable-next-line BCP318
var acrLoginServer = useExistingAcr ? existingAcr.properties.loginServer : newAcr.properties.loginServer

resource acrPullNew 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!useExistingAcr) {
  name: guid(resourceGroup().id, acrName, uami.id, acrPullRoleId)
  scope: newAcr
  properties: {
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
  }
}

resource acrPullExisting 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (useExistingAcr) {
  name: guid(resourceGroup().id, existingAcrName, uami.id, acrPullRoleId)
  scope: existingAcr
  properties: {
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
  }
}

// ── Storage (Azure Files for persistent state) ───────────────────────────────
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
  }
}

resource fileService 'Microsoft.Storage/storageAccounts/fileServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource fileShares 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-05-01' = [for s in shares: {
  parent: fileService
  name: s
  properties: {
    accessTier: 'TransactionOptimized'
    shareQuota: 5
  }
}]

// ── Key Vault (RBAC) + secrets ───────────────────────────────────────────────
resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: kvName
  location: location
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Enabled'
  }
}

// Secrets are written only when a value is supplied. Omit the params on
// redeploys and whatever is already in the vault is left untouched.
resource secretOpenAi 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(openAiApiKey)) {
  parent: kv
  name: 'OPENAI-API-KEY'
  properties: { value: openAiApiKey }
}

resource secretLangchain 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(langchainApiKey)) {
  parent: kv
  name: 'LANGCHAIN-API-KEY'
  properties: { value: langchainApiKey }
}

resource secretJira 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(jiraApiToken)) {
  parent: kv
  name: 'JIRA-API-TOKEN'
  properties: { value: jiraApiToken }
}

resource kvSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, uami.id, kvSecretsUserRoleId)
  scope: kv
  properties: {
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', kvSecretsUserRoleId)
  }
}

// ── Container Apps environment ───────────────────────────────────────────────
resource newEnv 'Microsoft.App/managedEnvironments@2024-03-01' = if (!useExistingEnv) {
  name: envName
  location: location
  properties: {
    // 'azure-monitor' hands log routing to the diagnostic setting below, so rows
    // land in the dedicated tables (ContainerAppConsoleLogs, ...SystemLogs,
    // ...HTTPLogs). The old 'log-analytics' destination wrote legacy custom
    // tables (ContainerAppConsoleLogs_CL / _SystemLogs_CL) with suffixed columns.
    appLogsConfiguration: {
      destination: 'azure-monitor'
    }
    zoneRedundant: false
  }
}

resource newEnvDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (!useExistingEnv) {
  name: 'container-app-logs'
  scope: newEnv
  properties: {
    #disable-next-line BCP318
    workspaceId: law.id
    logAnalyticsDestinationType: 'Dedicated'
    logs: [
      { category: 'ContainerAppConsoleLogs', enabled: true }
      { category: 'ContainerAppSystemLogs', enabled: true }
      { category: 'ContainerAppHTTPLogs', enabled: true }
    ]
  }
}

resource existingEnv 'Microsoft.App/managedEnvironments@2024-03-01' existing = if (useExistingEnv) {
  name: existingEnvironmentName
}

#disable-next-line BCP318
var environmentId = useExistingEnv ? existingEnv.id : newEnv.id

// Storage links are added to whichever environment is in use. Names are prefixed
// so they never collide with links that already exist on a shared environment.
resource envStorage 'Microsoft.App/managedEnvironments/storages@2024-03-01' = [for (s, i) in shares: {
  name: '${envNameEffective}/${namePrefix}-${s}'
  properties: {
    azureFile: {
      accountName: storage.name
      accountKey: storage.listKeys().keys[0].value
      shareName: s
      accessMode: 'ReadWrite'
    }
  }
  dependsOn: [
    fileShares[i]
    newEnv
  ]
}]

// ── Container App ────────────────────────────────────────────────────────────
resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  tags: { 'azd-service-name': 'web' }
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${uami.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: environmentId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8501
        transport: 'auto'
        allowInsecure: false
        stickySessions: { affinity: 'sticky' }
      }
      registries: [
        {
          server: acrLoginServer
          identity: uami.id
        }
      ]
      secrets: [
        {
          name: 'openai-api-key'
          keyVaultUrl: '${kv.properties.vaultUri}secrets/OPENAI-API-KEY'
          identity: uami.id
        }
        {
          name: 'langchain-api-key'
          keyVaultUrl: '${kv.properties.vaultUri}secrets/LANGCHAIN-API-KEY'
          identity: uami.id
        }
        {
          name: 'jira-api-token'
          keyVaultUrl: '${kv.properties.vaultUri}secrets/JIRA-API-TOKEN'
          identity: uami.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'brd-agent'
          image: containerImage
          resources: {
            cpu: json(cpu)
            memory: memory
          }
          env: [
            { name: 'OPENAI_API_KEY', secretRef: 'openai-api-key' }
            { name: 'LANGCHAIN_API_KEY', secretRef: 'langchain-api-key' }
            { name: 'JIRA_API_TOKEN', secretRef: 'jira-api-token' }
            { name: 'JIRA_SITE_URL', value: jiraSiteUrl }
            { name: 'JIRA_EMAIL', value: jiraEmail }
            { name: 'JIRA_PROJECT', value: jiraProject }
            { name: 'OPENAI_MODEL', value: openAiModel }
            { name: 'OPENAI_EMBED_MODEL', value: openAiEmbedModel }
            { name: 'LANGCHAIN_TRACING_V2', value: langchainTracing }
            { name: 'LANGCHAIN_PROJECT', value: langchainProject }
            { name: 'LANGCHAIN_ENDPOINT', value: langchainEndpoint }
            { name: 'VECTORSTORE_DIR', value: '/app/vectorstore' }
            { name: 'CHECKPOINT_DB', value: '/app/checkpoints/langgraph_states.db' }
            { name: 'APP_BUILD', value: imageTag }
            { name: 'ARTIFACT_STORE', value: 'local' }
            { name: 'LOG_LEVEL', value: 'INFO' }
            { name: 'AZURE_CLIENT_ID', value: uami.properties.clientId }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: aiConnectionString }
          ]
          volumeMounts: [
            { volumeName: 'vectorstore', mountPath: '/app/vectorstore' }
            { volumeName: 'output', mountPath: '/app/output' }
          ]
          // Liveness previously allowed only initialDelaySeconds(30) +
          // periodSeconds(30) x failureThreshold(6) = 210s of runway before
          // killing the container -- live-caught crash-looping a cold
          // replica that hadn't finished importing LangChain/LangGraph and
          // mounting the Azure Files shares within that window: Liveness
          // killed it, the fresh replica hit the same slow boot, and it
          // repeated every ~210s, never once reaching Readiness. Raised to
          // both platform-enforced caps -- initialDelaySeconds max 60,
          // failureThreshold max 10 (confirmed live: 90 was rejected with
          // ContainerAppProbeInitialDelaySecondsOutOfRange) -- giving ~360s
          // of runway, the most headroom these caps allow, so a single boot
          // attempt gets a real chance to finish before anything restarts it.
          probes: [
            {
              type: 'Liveness'
              httpGet: { path: '/_stcore/health', port: 8501 }
              initialDelaySeconds: 60
              periodSeconds: 30
              failureThreshold: 10
            }
            {
              type: 'Readiness'
              httpGet: { path: '/_stcore/health', port: 8501 }
              initialDelaySeconds: 60
              periodSeconds: 20
              failureThreshold: 10
            }
          ]
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
      }
      volumes: [
        { name: 'vectorstore', storageType: 'AzureFile', storageName: '${namePrefix}-vectorstore' }
        { name: 'output', storageType: 'AzureFile', storageName: '${namePrefix}-output' }
      ]
    }
  }
  dependsOn: [
    acrPullNew
    acrPullExisting
    kvSecretsUser
    secretOpenAi
    secretLangchain
    envStorage
  ]
}

// ── Outputs ──────────────────────────────────────────────────────────────────
output appUrl string = 'https://${app.properties.configuration.ingress.fqdn}'
output appName string = app.name
output environmentName string = envNameEffective
output acrName string = useExistingAcr ? existingAcrName : acrName
output acrLoginServer string = acrLoginServer
output keyVaultName string = kv.name
output resourceGroup string = resourceGroup().name
output managedIdentityClientId string = uami.properties.clientId
