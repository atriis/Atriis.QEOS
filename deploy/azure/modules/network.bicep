// The cluster's virtual network (ADR-038): one subnet for the AKS nodes and one delegated to PostgreSQL Flexible Server
// (private access). Pods do not take VNet addresses: Azure CNI Overlay gives them the pod range set in aks.bicep, which
// must not overlap these ranges.

param location string
param tags object
param name string

@description('The VNet address space.')
param addressPrefix string = '10.10.0.0/16'

@description('The AKS nodes. Their outbound traffic to Key Vault and Storage goes through service endpoints, which the vault and the storage account allow (pods leave the node with its address under Overlay).')
param nodesPrefix string = '10.10.0.0/22'

@description('Delegated to PostgreSQL Flexible Server; nothing else can use it.')
param postgresPrefix string = '10.10.8.0/27'

resource vnet 'Microsoft.Network/virtualNetworks@2026-01-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [addressPrefix]
    }
    subnets: [
      {
        name: 'aks-nodes'
        properties: {
          addressPrefix: nodesPrefix
          serviceEndpoints: [
            { service: 'Microsoft.KeyVault' }
            { service: 'Microsoft.Storage' }
          ]
        }
      }
      {
        name: 'postgres'
        properties: {
          addressPrefix: postgresPrefix
          delegations: [
            {
              name: 'postgres-flexible-server'
              properties: {
                serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers'
              }
            }
          ]
        }
      }
    ]
  }
}

output vnetId string = vnet.id
output nodesSubnetId string = vnet.properties.subnets[0].id
output postgresSubnetId string = vnet.properties.subnets[1].id
