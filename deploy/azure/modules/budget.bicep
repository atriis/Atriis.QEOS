// A monthly cost budget on the resource group (spec 5.1): email at 80% and 100% of actual spend.

param name string

@description('The monthly amount, in the billing currency.')
param amount int

@minLength(1)
param emails string[]

@description('The first day of a month, yyyy-MM-01; an existing budget keeps the date it was created with.')
param startDate string

resource budget 'Microsoft.Consumption/budgets@2026-06-01' = {
  name: name
  properties: {
    category: 'Cost'
    amount: amount
    timeGrain: 'Monthly'
    timePeriod: {
      startDate: startDate
    }
    notifications: {
      actual80: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 80
        thresholdType: 'Actual'
        contactEmails: emails
      }
      actual100: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 100
        thresholdType: 'Actual'
        contactEmails: emails
      }
    }
  }
}
