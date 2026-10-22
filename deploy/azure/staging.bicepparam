// AKS staging (ADR-038). Values that are secret, personal or per-operator come from the environment of the shell that
// runs `az deployment sub create` (deploy/azure/README.md, "Deploy"); nothing here is secret.
using 'main.bicep'

param environmentName = 'staging'
param location = 'westeurope'

// Comma-separated CIDRs, e.g. 203.0.113.7/32,198.51.100.0/24: the API server, Key Vault and Storage admit them
param apiServerAuthorizedIpRanges = split(readEnvironmentVariable('QEOS_ADMIN_IP_RANGES'), ',')
param operatorIpRanges = split(readEnvironmentVariable('QEOS_ADMIN_IP_RANGES'), ',')

// Object ids (empty: skipped): the operator who runs init-secrets.sh, the AKS admin group, the GitHub OIDC application's
// service principal, and the ACS SMTP application (README, one-time steps)
param operatorPrincipalId = readEnvironmentVariable('QEOS_OPERATOR_PRINCIPAL_ID', '')
param aksAdminGroupObjectIds = empty(readEnvironmentVariable('QEOS_AKS_ADMIN_GROUP_ID', ''))
  ? []
  : [readEnvironmentVariable('QEOS_AKS_ADMIN_GROUP_ID', '')]
param deployPrincipalId = readEnvironmentVariable('QEOS_DEPLOY_PRINCIPAL_ID', '')
param smtpAppClientId = readEnvironmentVariable('QEOS_SMTP_APP_CLIENT_ID', '')
param smtpAppPrincipalId = readEnvironmentVariable('QEOS_SMTP_APP_PRINCIPAL_ID', '')

// The first deploy: a new random value. Every later one: the value Key Vault holds (README)
param postgresAdminPassword = readEnvironmentVariable('QEOS_POSTGRES_ADMIN_PASSWORD')

// Small sizes (spec 5.14): one system node, two to four user nodes, a B1ms server; stopped outside working hours
param aksSkuTier = 'Free'
param systemNodeVmSize = 'Standard_D2as_v5'
param systemNodeCount = 1
param userNodeVmSize = 'Standard_D2as_v5'
param userNodeMinCount = 2
param userNodeMaxCount = 4
param acrSku = 'Basic'
param postgresSkuName = 'Standard_B1ms'
param postgresSkuTier = 'Burstable'
param postgresStorageGB = 32
param storageSku = 'Standard_LRS'
// Staging's vault can be deleted and recreated under the same name after a teardown
param keyVaultPurgeProtection = false

param emailDataLocation = 'Europe'

param monthlyBudget = 300
param budgetEmails = split(readEnvironmentVariable('QEOS_BUDGET_EMAILS'), ',')
param budgetStartDate = '2026-11-01'
