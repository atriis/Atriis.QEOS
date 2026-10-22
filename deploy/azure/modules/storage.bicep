// The artifact store (spec 5.5, AzureBlobArtifactStore): one private container, Entra ID only (no account keys, no SAS,
// no anonymous access), TLS 1.2, soft delete and versioning for restores. The ingestion service and the retention job
// write, copy and batch-delete with Storage Blob Data Contributor on the container.

param location string
param tags object

@description('3-24 lowercase letters and digits, globally unique.')
param name string

@allowed(['Standard_LRS', 'Standard_ZRS', 'Standard_GRS'])
param sku string = 'Standard_LRS'

@description('The chart\'s artifacts.azure.container.')
param containerName string

@description('The AKS node subnet (service endpoint Microsoft.Storage).')
param nodesSubnetId string

@description('Operators\' public IPv4 addresses or CIDR ranges (restore drills, az storage).')
param operatorIpRanges string[] = []

@description('The identities that read and write artifacts, by name and principal id, in the same order.')
param writerNames string[]
param writerPrincipalIds string[]

@description('Days a deleted blob, container or previous version stays restorable.')
param retentionDays int = 14

var blobDataContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'

resource account 'Microsoft.Storage/storageAccounts@2026-06-01' = {
  name: name
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: {
    name: sku
  }
  properties: {
    accessTier: 'Hot'
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    allowBlobPublicAccess: false
    allowCrossTenantReplication: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'AzureServices'
      virtualNetworkRules: [
        {
          id: nodesSubnetId
          action: 'Allow'
        }
      ]
      // Storage takes single addresses without /32
      ipRules: [for range in operatorIpRanges: { value: replace(range, '/32', ''), action: 'Allow' }]
    }
  }
}

resource blobs 'Microsoft.Storage/storageAccounts/blobServices@2026-06-01' = {
  parent: account
  name: 'default'
  properties: {
    isVersioningEnabled: true
    deleteRetentionPolicy: {
      enabled: true
      days: retentionDays
    }
    containerDeleteRetentionPolicy: {
      enabled: true
      days: retentionDays
    }
  }
}

resource container 'Microsoft.Storage/storageAccounts/blobServices/containers@2026-06-01' = {
  parent: blobs
  name: containerName
  properties: {
    publicAccess: 'None'
  }
}

// Versioning keeps every overwritten or deleted blob: previous versions go after the same retention
resource lifecycle 'Microsoft.Storage/storageAccounts/managementPolicies@2026-06-01' = {
  parent: account
  name: 'default'
  properties: {
    policy: {
      rules: [
        {
          name: 'expire-previous-versions'
          enabled: true
          type: 'Lifecycle'
          definition: {
            filters: {
              blobTypes: ['blockBlob']
            }
            actions: {
              version: {
                delete: {
                  daysAfterCreationGreaterThan: retentionDays
                }
              }
            }
          }
        }
      ]
    }
  }
}

resource writers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for (writer, i) in writerNames: {
    name: guid(container.id, writer, blobDataContributor)
    scope: container
    properties: {
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataContributor)
      principalId: writerPrincipalIds[i]
      principalType: 'ServicePrincipal'
    }
  }
]

output blobEndpoint string = account.properties.primaryEndpoints.blob
output containerName string = container.name
