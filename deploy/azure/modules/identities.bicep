// One user-assigned managed identity per workload identity the chart uses (keyvault.clientIds), each federated with its
// ServiceAccount qeos-<identity> in the release namespace (workload identity). The chart puts the client ids on the
// ServiceAccounts and in the SecretProviderClasses.

param location string
param tags object
param namePrefix string

@description('The chart\'s identity names: services, ingestion, ingestion-retention, migrate.')
param identityNames string[]

@description('The AKS OIDC issuer URL.')
param oidcIssuerUrl string

@description('The Kubernetes namespace the chart is installed in.')
param namespace string

resource identities 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = [
  for identity in identityNames: {
    name: '${namePrefix}-${identity}'
    location: location
    tags: tags
  }
]

resource federated 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2024-11-30' = [
  for (identity, i) in identityNames: {
    parent: identities[i]
    name: 'aks-${namespace}-qeos-${identity}'
    properties: {
      issuer: oidcIssuerUrl
      subject: 'system:serviceaccount:${namespace}:qeos-${identity}'
      audiences: ['api://AzureADTokenExchange']
    }
  }
]

// In the order of identityNames
output clientIds string[] = [for (identity, i) in identityNames: identities[i].properties.clientId]
output principalIds string[] = [for (identity, i) in identityNames: identities[i].properties.principalId]
