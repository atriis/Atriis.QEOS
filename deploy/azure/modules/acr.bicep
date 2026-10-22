// Azure Container Registry (spec 5.2): the kubelet pulls with AcrPull (no pull secret); the GitHub build identity pushes
// with AcrPush, and the GitHub deploy identity reads with AcrPull (it checks the images exist). No admin user, no anonymous pull. The untagged-manifest retention policy needs Premium; on Basic and Standard
// the runbook's scheduled `acr purge` task removes old images instead.

param location string
param tags object

@description('Globally unique, 5-50 letters and digits.')
param name string

@allowed(['Basic', 'Standard', 'Premium'])
param sku string = 'Basic'

@description('The AKS kubelet identity\'s object id.')
param kubeletObjectId string

@description('The GitHub build identity (service principal object id): AcrPush. Empty: no push role.')
param buildPrincipalId string = ''

@description('The GitHub deploy identity (service principal object id): AcrPull, to check the images. Empty: none.')
param deployPrincipalId string = ''

var acrPull = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var acrPush = '8311e382-0749-4cb8-b61a-ed27ecc9c4fc'

resource registry 'Microsoft.ContainerRegistry/registries@2025-11-01' = {
  name: name
  location: location
  tags: tags
  sku: {
    name: sku
  }
  properties: {
    adminUserEnabled: false
    anonymousPullEnabled: false
    policies: sku == 'Premium'
      ? {
          retentionPolicy: {
            status: 'enabled'
            days: 7
          }
        }
      : null
  }
}

resource kubeletPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, 'kubelet', acrPull)
  scope: registry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPull)
    principalId: kubeletObjectId
    principalType: 'ServicePrincipal'
  }
}

resource buildPush 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(buildPrincipalId)) {
  name: guid(registry.id, buildPrincipalId, acrPush)
  scope: registry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPush)
    principalId: buildPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource deployPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deployPrincipalId)) {
  name: guid(registry.id, deployPrincipalId, acrPull)
  scope: registry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPull)
    principalId: deployPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output name string = registry.name
