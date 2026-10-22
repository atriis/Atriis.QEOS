// QEOS on AKS (ADR-038, spec 5.1): the Azure resources of one environment, in a resource group of their own. Deploy with
// `az deployment sub create` and the environment's .bicepparam (deploy/azure/README.md). The outputs are what the Helm
// chart (--set) and the GitHub workflows (repository variables) consume.

targetScope = 'subscription'

@allowed(['staging', 'production'])
param environmentName string

param location string

param resourceGroupName string = 'rg-qeos-${environmentName}'

@description('The Kubernetes namespace the chart is installed in: the workload identities trust its ServiceAccounts only.')
param namespace string = 'qeos'

@description('CIDR ranges allowed to reach the AKS API server (operators). The deploy workflow adds its runner for the run.')
@minLength(1)
param apiServerAuthorizedIpRanges string[]

@description('Operators\' public IPv4 addresses or CIDR ranges allowed to the Key Vault and Storage data planes.')
param operatorIpRanges string[] = []

@description('An operator (user or group object id) given Key Vault Secrets Officer, to run init-secrets.sh. Empty: none.')
param operatorPrincipalId string = ''

@description('Entra ID groups that are AKS cluster admins.')
param aksAdminGroupObjectIds string[] = []

@description('The GitHub build application\'s service principal object id (AZURE_BUILD_CLIENT_ID): AcrPush. Empty: none.')
param buildPrincipalId string = ''

@description('The GitHub deploy application\'s service principal object id (AZURE_DEPLOY_CLIENT_ID), trusted for GitHub environments only: AcrPull and the cluster roles the deploy workflow needs. Empty: none.')
param deployPrincipalId string = ''

@description('Empty: the region\'s default Kubernetes version.')
param kubernetesVersion string = ''

@allowed(['Free', 'Standard'])
param aksSkuTier string = 'Free'

param systemNodeVmSize string = 'Standard_D2as_v5'
param systemNodeCount int = 1
param userNodeVmSize string = 'Standard_D2as_v5'
param userNodeMinCount int = 2
param userNodeMaxCount int = 4

@allowed(['Basic', 'Standard', 'Premium'])
param acrSku string = 'Basic'

param postgresSkuName string = 'Standard_B1ms'

@allowed(['Burstable', 'GeneralPurpose', 'MemoryOptimized'])
param postgresSkuTier string = 'Burstable'

param postgresVersion string = '16'
param postgresStorageGB int = 32

@description('The chart\'s postgres.adminUser.')
param postgresAdminLogin string = 'qeosadmin'

@description('Written to Key Vault as postgres-admin-password. On a redeploy, pass the value the vault holds (README).')
@secure()
@minLength(16)
param postgresAdminPassword string

@allowed(['Standard_LRS', 'Standard_ZRS', 'Standard_GRS'])
param storageSku string = 'Standard_LRS'

param emailDataLocation string = 'Europe'

@description('The ACS SMTP Entra application\'s client id (README, one-time steps). Empty: no SMTP username yet.')
param smtpAppClientId string = ''

@description('That application\'s service principal object id. Empty: no send role yet.')
param smtpAppPrincipalId string = ''

@description('True once init-secrets.sh has created the secrets it generates (README, section 3.1): only then can each identity be given read access to each one.')
param generatedSecretsExist bool = false

@description('The monthly budget of the resource group, in the billing currency.')
param monthlyBudget int

@minLength(1)
param budgetEmails string[]

@description('yyyy-MM-01: the first day of the month the budget starts.')
param budgetStartDate string

param tags object = {}

// The chart's workload identities (values.yaml keyvault.clientIds; ServiceAccounts qeos-<identity>).
// scripts/tests/test_azure_bicep.py keeps this list equal to the chart's
var workloadIdentities = [
  'services'
  'ingestion'
  'ingestion-retention'
  'migrate'
]

// The identities that read and write artifacts (values.yaml azureSdk: true)
var artifactWriters = [
  'ingestion'
  'ingestion-retention'
]

// Who reads each Key Vault secret: the identities whose SecretProviderClasses list it (the chart's per-workload key
// lists, plus the migration hook's). Key Vault Secrets User is granted per secret, never on the whole vault.
// scripts/tests/test_azure_bicep.py keeps this map equal to the chart's
var secretReaders = {
  'postgres-admin-password': ['migrate']
  'secret-key': ['services', 'ingestion', 'ingestion-retention', 'migrate']
  'internal-api-password': ['services', 'ingestion', 'ingestion-retention']
  'auth-db-password': ['services', 'migrate']
  'organization-db-password': ['services', 'migrate']
  'project-db-password': ['services', 'migrate']
  'testmgmt-db-password': ['services', 'migrate']
  'ingestion-db-password': ['services', 'ingestion', 'ingestion-retention', 'migrate']
  'smtp-user': ['services', 'ingestion', 'ingestion-retention']
  'smtp-password': ['services', 'ingestion', 'ingestion-retention']
}

// A role on a secret needs the secret: Bicep's own now, init-secrets.sh's once they exist, SMTP's once the SMTP
// application is set up (smtp-password is written before that redeploy, README section 4.1)
var smtpSecrets = ['smtp-user', 'smtp-password']
var grantedSecrets = filter(
  objectKeys(secretReaders),
  secret => secret == 'postgres-admin-password' || (contains(smtpSecrets, secret) ? !empty(smtpAppClientId) : generatedSecretsExist)
)
var secretGrants = flatten(map(grantedSecrets, secret => map(secretReaders[secret], identity => { secret: secret, identity: identity })))

// The chart's artifacts.azure.container
var artifactsContainer = 'qeos-artifacts'

// The chart's gateway.trustedProxies in values-staging.yaml: the edge's pods are in this range
var podCidr = '10.244.0.0/16'

var allTags = union(tags, { application: 'qeos', environment: environmentName })
var prefix = 'qeos-${environmentName}'
var suffix = uniqueString(subscription().id, resourceGroupName)
var vnetName = 'vnet-${prefix}'
// The SMTP username, once the ACS SMTP application exists (README); smtp-user in Key Vault
var smtpUsername = empty(smtpAppClientId) ? '' : prefix

resource group 'Microsoft.Resources/resourceGroups@2025-04-01' = {
  name: resourceGroupName
  location: location
  tags: allTags
}

module network 'modules/network.bicep' = {
  scope: group
  params: {
    location: location
    tags: allTags
    name: vnetName
  }
}

module aks 'modules/aks.bicep' = {
  scope: group
  params: {
    location: location
    tags: allTags
    name: 'aks-${prefix}'
    vnetName: vnetName
    podCidr: podCidr
    apiServerAuthorizedIpRanges: apiServerAuthorizedIpRanges
    adminGroupObjectIds: aksAdminGroupObjectIds
    kubernetesVersion: kubernetesVersion
    skuTier: aksSkuTier
    systemNodeVmSize: systemNodeVmSize
    systemNodeCount: systemNodeCount
    userNodeVmSize: userNodeVmSize
    userNodeMinCount: userNodeMinCount
    userNodeMaxCount: userNodeMaxCount
    deployPrincipalId: deployPrincipalId
    namespace: namespace
    edgeDnsLabel: '${prefix}-${take(suffix, 6)}'
  }
  // The node subnet must exist: the module takes it by name
  dependsOn: [network]
}

module acr 'modules/acr.bicep' = {
  scope: group
  params: {
    location: location
    tags: allTags
    name: 'acrqeos${take(environmentName, 4)}${suffix}'
    sku: acrSku
    kubeletObjectId: aks.outputs.kubeletObjectId
    buildPrincipalId: buildPrincipalId
    deployPrincipalId: deployPrincipalId
  }
}

module identities 'modules/identities.bicep' = {
  scope: group
  params: {
    location: location
    tags: allTags
    namePrefix: 'id-${prefix}'
    identityNames: workloadIdentities
    oidcIssuerUrl: aks.outputs.oidcIssuerUrl
    namespace: namespace
  }
}

module postgres 'modules/postgres.bicep' = {
  scope: group
  params: {
    location: location
    tags: allTags
    name: 'psql-${prefix}-${take(suffix, 6)}'
    vnetId: network.outputs.vnetId
    subnetId: network.outputs.postgresSubnetId
    skuName: postgresSkuName
    skuTier: postgresSkuTier
    version: postgresVersion
    storageSizeGB: postgresStorageGB
    adminLogin: postgresAdminLogin
    adminPassword: postgresAdminPassword
  }
}

module storage 'modules/storage.bicep' = {
  scope: group
  params: {
    location: location
    tags: allTags
    name: 'stqeos${take(environmentName, 4)}${take(suffix, 10)}'
    sku: storageSku
    containerName: artifactsContainer
    nodesSubnetId: network.outputs.nodesSubnetId
    operatorIpRanges: operatorIpRanges
    writerNames: artifactWriters
    writerPrincipalIds: [for writer in artifactWriters: identities.outputs.principalIds[indexOf(workloadIdentities, writer)]]
  }
}

module email 'modules/email.bicep' = {
  scope: group
  params: {
    tags: allTags
    name: 'acs-${prefix}-${take(suffix, 6)}'
    dataLocation: emailDataLocation
    smtpAppClientId: smtpAppClientId
    smtpAppPrincipalId: smtpAppPrincipalId
    smtpUsername: prefix
  }
}

module keyvault 'modules/keyvault.bicep' = {
  scope: group
  params: {
    location: location
    tags: allTags
    name: 'kv-${take(prefix, 12)}-${take(suffix, 8)}'
    nodesSubnetId: network.outputs.nodesSubnetId
    operatorIpRanges: operatorIpRanges
    readerNames: workloadIdentities
    readerPrincipalIds: identities.outputs.principalIds
    secretGrants: secretGrants
    operatorPrincipalId: operatorPrincipalId
    postgresAdminPassword: postgresAdminPassword
    smtpUsername: smtpUsername
  }
}

module budget 'modules/budget.bicep' = {
  scope: group
  params: {
    name: 'budget-${prefix}'
    amount: monthlyBudget
    emails: budgetEmails
    startDate: budgetStartDate
  }
}

output acrName string = acr.outputs.name
output aksName string = aks.outputs.name
output resourceGroup string = group.name
output keyVaultName string = keyvault.outputs.name
output postgresHost string = postgres.outputs.host
output storageAccountUrl string = storage.outputs.blobEndpoint
output artifactsContainer string = storage.outputs.containerName
output workloadIdentityClientIds object = toObject(
  range(0, length(workloadIdentities)),
  i => workloadIdentities[i],
  i => identities.outputs.clientIds[i]
)
output communicationEmailSender string = email.outputs.sender
// The edge's address (a static public IP with a DNS label, kept across cluster stops and rebuilds): the chart's
// publicUrl is https://<stagingHostname>
output stagingHostname string = aks.outputs.edgeHostname
