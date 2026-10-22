// The AKS cluster (ADR-038, spec 5.1): Azure CNI Overlay powered by Cilium (so NetworkPolicies are enforced), workload
// identity with the OIDC issuer, the Key Vault Secrets Store CSI add-on, the Application Routing add-on's Gateway API
// implementation, Entra ID sign-in with Kubernetes RBAC through Azure RBAC (no local accounts), an API server open only
// to authorised IP ranges, automatic patch and node image upgrades in a Sunday-night window, and Defender for Containers.

param location string
param tags object
param name string

@description('The VNet of network.bicep; the nodes go in its subnet aks-nodes.')
param vnetName string

@description('The pod range of Azure CNI Overlay. The chart trusts the edge by this range (values-staging.yaml gateway.trustedProxies): change both together.')
param podCidr string

@description('Address ranges (CIDR) allowed to reach the API server. The deploy workflow adds its runner for the run.')
@minLength(1)
param apiServerAuthorizedIpRanges string[]

@description('Entra ID groups that are cluster admins.')
param adminGroupObjectIds string[] = []

@description('Empty: the default version of the region.')
param kubernetesVersion string = ''

@allowed(['Free', 'Standard'])
param skuTier string = 'Free'

param systemNodeVmSize string = 'Standard_D2as_v5'
param systemNodeCount int = 1
param userNodeVmSize string = 'Standard_D2as_v5'
param userNodeMinCount int = 2
param userNodeMaxCount int = 4

@description('The GitHub deploy identity (service principal object id). Empty: no role on the cluster.')
param deployPrincipalId string = ''

var roles = {
  networkContributor: '4d97b98b-1d4f-4787-a291-c67834d212e7'
  aksClusterUser: '4abbcc35-e782-43d8-92c5-2d3f1bd2253f'
  aksRbacClusterAdmin: 'b1ff04bb-8a4e-4dc4-8eb5-8693973ce19b'
  aksContributor: 'ed7f3fbd-7b88-4dd4-9017-9adb7ce333f8'
}

// Defender for Containers' sensor and, later, Container Insights (Stage 2) write here
resource logs 'Microsoft.OperationalInsights/workspaces@2026-03-01' = {
  name: 'log-${name}'
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

// The control plane's own identity: a user-assigned one, so it can be given Network Contributor on the node subnet
// before the cluster exists (a bring-your-own subnet needs it for load balancers and routes)
resource controlPlane 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: 'id-${name}-control-plane'
  location: location
  tags: tags
}

resource vnet 'Microsoft.Network/virtualNetworks@2026-01-01' existing = {
  name: vnetName
}

resource nodesSubnet 'Microsoft.Network/virtualNetworks/subnets@2026-01-01' existing = {
  parent: vnet
  name: 'aks-nodes'
}

resource controlPlaneNetwork 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(nodesSubnet.id, controlPlane.id, roles.networkContributor)
  scope: nodesSubnet
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.networkContributor)
    principalId: controlPlane.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource cluster 'Microsoft.ContainerService/managedClusters@2026-06-01' = {
  name: name
  location: location
  tags: tags
  sku: {
    name: 'Base'
    tier: skuTier
  }
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${controlPlane.id}': {}
    }
  }
  properties: {
    kubernetesVersion: empty(kubernetesVersion) ? null : kubernetesVersion
    dnsPrefix: name
    enableRBAC: true
    disableLocalAccounts: true
    aadProfile: {
      managed: true
      enableAzureRBAC: true
      adminGroupObjectIDs: adminGroupObjectIds
      tenantID: tenant().tenantId
    }
    apiServerAccessProfile: {
      authorizedIPRanges: apiServerAuthorizedIpRanges
    }
    agentPoolProfiles: [
      {
        // Add-ons only: the taint keeps QEOS's pods on the user pool
        name: 'system'
        mode: 'System'
        type: 'VirtualMachineScaleSets'
        vmSize: systemNodeVmSize
        count: systemNodeCount
        osType: 'Linux'
        osSKU: 'AzureLinux'
        vnetSubnetID: nodesSubnet.id
        nodeTaints: ['CriticalAddonsOnly=true:NoSchedule']
      }
      {
        name: 'user'
        mode: 'User'
        type: 'VirtualMachineScaleSets'
        vmSize: userNodeVmSize
        count: userNodeMinCount
        enableAutoScaling: true
        minCount: userNodeMinCount
        maxCount: userNodeMaxCount
        osType: 'Linux'
        osSKU: 'AzureLinux'
        vnetSubnetID: nodesSubnet.id
      }
    ]
    networkProfile: {
      networkPlugin: 'azure'
      networkPluginMode: 'overlay'
      networkDataplane: 'cilium'
      networkPolicy: 'cilium'
      podCidr: podCidr
      serviceCidr: '10.0.0.0/16'
      dnsServiceIP: '10.0.0.10'
      loadBalancerSku: 'standard'
      outboundType: 'loadBalancer'
    }
    oidcIssuerProfile: {
      enabled: true
    }
    securityProfile: {
      workloadIdentity: {
        enabled: true
      }
      defender: {
        logAnalyticsWorkspaceResourceId: logs.id
        securityMonitoring: {
          enabled: true
        }
      }
      imageCleaner: {
        enabled: true
        intervalHours: 168
      }
    }
    addonProfiles: {
      azureKeyvaultSecretsProvider: {
        enabled: true
        config: {
          enableSecretRotation: 'true'
          rotationPollInterval: '2m'
        }
      }
    }
    // The Application Routing add-on's Gateway API implementation (GatewayClass approuting-istio) on the managed
    // Gateway API CRDs. Its NGINX Ingress controller stays off: Microsoft supports it only until November 2026
    ingressProfile: {
      gatewayAPI: {
        installation: 'Standard'
      }
      webAppRouting: {
        gatewayAPIImplementations: {
          appRoutingIstio: {
            mode: 'Enabled'
          }
        }
      }
    }
    autoUpgradeProfile: {
      upgradeChannel: 'patch'
      nodeOSUpgradeChannel: 'NodeImage'
    }
  }
  dependsOn: [controlPlaneNetwork]
}

// Sunday 01:00-05:00 UTC for both the Kubernetes patch upgrades and the node image upgrades
var sundayNight = {
  schedule: {
    weekly: {
      dayOfWeek: 'Sunday'
      intervalWeeks: 1
    }
  }
  startTime: '01:00'
  durationHours: 4
  utcOffset: '+00:00'
}

resource upgradeWindow 'Microsoft.ContainerService/managedClusters/maintenanceConfigurations@2026-06-01' = {
  parent: cluster
  name: 'aksManagedAutoUpgradeSchedule'
  properties: {
    maintenanceWindow: sundayNight
  }
}

resource nodeOsWindow 'Microsoft.ContainerService/managedClusters/maintenanceConfigurations@2026-06-01' = {
  parent: cluster
  name: 'aksManagedNodeOSUpgradeSchedule'
  properties: {
    maintenanceWindow: sundayNight
  }
  dependsOn: [upgradeWindow]
}

// The deploy workflow: kubeconfig (Cluster User), helm (RBAC Cluster Admin: the chart and cert-manager), and adding
// its runner to the authorised IP ranges for the run (AKS Contributor)
var deployRoles = empty(deployPrincipalId) ? [] : [roles.aksClusterUser, roles.aksRbacClusterAdmin, roles.aksContributor]

resource deployAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for role in deployRoles: {
    name: guid(cluster.id, deployPrincipalId, role)
    scope: cluster
    properties: {
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', role)
      principalId: deployPrincipalId
      principalType: 'ServicePrincipal'
    }
  }
]

output name string = cluster.name
output oidcIssuerUrl string = cluster.properties.oidcIssuerProfile.issuerURL
output kubeletObjectId string = cluster.properties.identityProfile.kubeletidentity.objectId
