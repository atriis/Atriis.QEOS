// Email (spec 5.9): Azure Communication Services with an Email Communication Service and its Azure-managed sender
// domain (DoNotReply@<guid>.azurecomm.net). The chart sends through smtp.azurecomm.net:587 with the SMTP_* settings.
// SMTP signs in with a Microsoft Entra application, which Bicep cannot create (runbook): once it exists, its client id
// and service principal object id make Bicep add the SMTP username and the send role; its client secret is the password.

param tags object
param name string

@description('Where ACS stores data at rest, e.g. Europe, UnitedStates.')
param dataLocation string = 'Europe'

@description('The Entra application\'s client (app) id. Empty: no SMTP username yet.')
param smtpAppClientId string = ''

@description('The Entra application\'s service principal object id. Empty: no role yet.')
param smtpAppPrincipalId string = ''

@description('The SMTP username (free text); the chart\'s smtp-user.')
param smtpUsername string

resource emailService 'Microsoft.Communication/emailServices@2026-03-18' = {
  name: 'email-${name}'
  location: 'global'
  tags: tags
  properties: {
    dataLocation: dataLocation
  }
}

resource domain 'Microsoft.Communication/emailServices/domains@2026-03-18' = {
  parent: emailService
  name: 'AzureManagedDomain'
  location: 'global'
  tags: tags
  properties: {
    domainManagement: 'AzureManaged'
    userEngagementTracking: 'Disabled'
  }
}

resource communication 'Microsoft.Communication/communicationServices@2026-03-18' = {
  name: name
  location: 'global'
  tags: tags
  properties: {
    dataLocation: dataLocation
    linkedDomains: [domain.id]
    // No access keys: SMTP signs in with Entra ID
    disableLocalAuth: true
  }
}

resource smtpUser 'Microsoft.Communication/communicationServices/smtpUsernames@2026-03-18' = if (!empty(smtpAppClientId)) {
  parent: communication
  name: smtpUsername
  properties: {
    username: smtpUsername
    entraApplicationId: smtpAppClientId
    tenantId: tenant().tenantId
  }
}

// The three permissions ACS documents for SMTP, instead of the broad Communication and Email Service Owner
resource sendRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' = {
  name: guid(resourceGroup().id, 'qeos-acs-smtp-send')
  properties: {
    roleName: 'QEOS SMTP sender (${resourceGroup().name})'
    description: 'Send email through Azure Communication Services SMTP.'
    type: 'CustomRole'
    assignableScopes: [resourceGroup().id]
    permissions: [
      {
        actions: [
          'Microsoft.Communication/CommunicationServices/Read'
          'Microsoft.Communication/CommunicationServices/Write'
          'Microsoft.Communication/EmailServices/write'
        ]
        notActions: []
      }
    ]
  }
}

resource smtpSender 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(smtpAppPrincipalId)) {
  name: guid(communication.id, smtpAppPrincipalId, sendRole.id)
  scope: communication
  properties: {
    roleDefinitionId: sendRole.id
    principalId: smtpAppPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output sender string = 'DoNotReply@${domain.properties.mailFromSenderDomain}'
