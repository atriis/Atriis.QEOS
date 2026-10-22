// PostgreSQL Flexible Server (spec 5.5): private access only, in a subnet of the cluster's VNet with its private DNS
// zone; TLS 1.2 or newer required; 35 days of backups for point-in-time restore; pg_stat_statements allowed
// (postgres-exporter, Stage 2). The migration hook's db-init creates the five databases and their roles with the admin login.

param location string
param tags object
param name string

param vnetId string
param subnetId string

@description('Burstable B-series for staging; GeneralPurpose for production.')
param skuName string = 'Standard_B1ms'

@allowed(['Burstable', 'GeneralPurpose', 'MemoryOptimized'])
param skuTier string = 'Burstable'

param version string = '16'
param storageSizeGB int = 32

@description('The chart\'s postgres.adminUser.')
param adminLogin string

@secure()
param adminPassword string

// Flexible Server requires a zone name ending in .postgres.database.azure.com
resource dnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: '${name}.private.postgres.database.azure.com'
  location: 'global'
  tags: tags
}

resource dnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: dnsZone
  name: 'cluster-vnet'
  location: 'global'
  tags: tags
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnetId
    }
  }
}

resource server 'Microsoft.DBforPostgreSQL/flexibleServers@2025-08-01' = {
  name: name
  location: location
  tags: tags
  sku: {
    name: skuName
    tier: skuTier
  }
  properties: {
    version: version
    administratorLogin: adminLogin
    administratorLoginPassword: adminPassword
    authConfig: {
      passwordAuth: 'Enabled'
      activeDirectoryAuth: 'Disabled'
    }
    storage: {
      storageSizeGB: storageSizeGB
      autoGrow: 'Enabled'
    }
    backup: {
      backupRetentionDays: 35
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: {
      mode: 'Disabled'
    }
    network: {
      delegatedSubnetResourceId: subnetId
      privateDnsZoneArmResourceId: dnsZone.id
      publicNetworkAccess: 'Disabled'
    }
    // Sunday 01:00 UTC, with the cluster's window
    maintenanceWindow: {
      customWindow: 'Enabled'
      dayOfWeek: 0
      startHour: 1
      startMinute: 0
    }
  }
  dependsOn: [dnsLink]
}

// Server parameters one at a time: the server rejects concurrent updates
resource extensions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-08-01' = {
  parent: server
  name: 'azure.extensions'
  properties: {
    value: 'PG_STAT_STATEMENTS'
    source: 'user-override'
  }
}

// Flexible Server already preloads pg_stat_statements (shared_preload_libraries' platform default), so that static
// parameter is left alone: no restart

// The server defaults, pinned: no plaintext connection, nothing older than TLS 1.2
resource requireTls 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-08-01' = {
  parent: server
  name: 'require_secure_transport'
  properties: {
    value: 'ON'
    source: 'user-override'
  }
  dependsOn: [extensions]
}

resource minTls 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2025-08-01' = {
  parent: server
  name: 'ssl_min_protocol_version'
  properties: {
    value: 'TLSv1.2'
    source: 'user-override'
  }
  dependsOn: [requireTls]
}

output host string = server.properties.fullyQualifiedDomainName
