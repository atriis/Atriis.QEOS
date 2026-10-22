// Key Vault in RBAC mode (spec 5.6): every workload identity reads secrets (Key Vault Secrets User) through the Secrets
// Store CSI driver. Bicep writes the secrets it knows (the PostgreSQL admin password, the SMTP username); the runbook's
// init-secrets.sh generates the rest once. The data plane is open only to the AKS node subnet and the operators' ranges.

param location string
param tags object

@description('3-24 letters, digits and hyphens, globally unique.')
param name string

@description('The AKS node subnet (service endpoint Microsoft.KeyVault).')
param nodesSubnetId string

@description('Operators\' public IPv4 addresses or CIDR ranges, for init-secrets.sh and az keyvault.')
param operatorIpRanges string[] = []

@description('The identities that read secrets (identities.bicep), by name and principal id, in the same order.')
param readerNames string[]
param readerPrincipalIds string[]

@description('An operator (user or group object id) who manages secrets. Empty: none.')
param operatorPrincipalId string = ''

@description('Purge protection cannot be turned off again once on.')
param purgeProtection bool = true

@secure()
param postgresAdminPassword string

@description('The ACS SMTP username (email.bicep). Empty: smtp-user is not written.')
param smtpUsername string = ''

var secretsUser = '4633458b-17de-408a-b874-0445c86b69e6'
var secretsOfficer = 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'

resource vault 'Microsoft.KeyVault/vaults@2026-05-15' = {
  name: name
  location: location
  tags: tags
  properties: {
    tenantId: tenant().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    enablePurgeProtection: purgeProtection ? true : null
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'AzureServices'
      virtualNetworkRules: [
        {
          id: nodesSubnetId
        }
      ]
      ipRules: [for range in operatorIpRanges: { value: range }]
    }
  }
}

// The key the chart's migration hook (db-init) reads
resource postgresAdmin 'Microsoft.KeyVault/vaults/secrets@2026-05-15' = {
  parent: vault
  name: 'postgres-admin-password'
  properties: {
    value: postgresAdminPassword
    contentType: 'text/plain'
  }
}

resource smtpUser 'Microsoft.KeyVault/vaults/secrets@2026-05-15' = if (!empty(smtpUsername)) {
  parent: vault
  name: 'smtp-user'
  properties: {
    value: smtpUsername
    contentType: 'text/plain'
  }
}

resource readers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for (reader, i) in readerNames: {
    name: guid(vault.id, reader, secretsUser)
    scope: vault
    properties: {
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', secretsUser)
      principalId: readerPrincipalIds[i]
      principalType: 'ServicePrincipal'
    }
  }
]

resource operator 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(operatorPrincipalId)) {
  name: guid(vault.id, operatorPrincipalId, secretsOfficer)
  scope: vault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', secretsOfficer)
    principalId: operatorPrincipalId
  }
}

output name string = vault.name
