targetScope = 'resourceGroup'
@description('Azure region of the existing AML workspace and Event Grid system topic.')
param location string = resourceGroup().location


@description('Existing Azure ML workspace name.')
param workspaceName string

@description('Existing Azure Function App name. Deploy the function package before this template.')
param functionAppName string

@description('Existing storage account for dead-letter events.')
param storageAccountName string

@description('User-assigned identity resource ID with Storage Blob Data Contributor on the dead-letter container.')
param eventGridIdentityId string

resource workspace 'Microsoft.MachineLearningServices/workspaces@2025-09-01' existing = {
  name: workspaceName
}

resource functionApp 'Microsoft.Web/sites@2024-04-01' existing = {
  name: functionAppName
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: storageAccountName
}

resource amlSystemTopic 'Microsoft.EventGrid/systemTopics@2025-02-15' = {
  name: take('${workspaceName}-monitor-events', 50)
  location: location
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${eventGridIdentityId}': {}
    }
  }
  properties: {
    source: workspace.id
    topicType: 'Microsoft.MachineLearningServices.Workspaces'
  }
}

resource amlMonitorEvents 'Microsoft.EventGrid/eventSubscriptions@2025-02-15' = {
  name: 'aml-model-monitor-events'
  scope: amlSystemTopic
  properties: {
    deadLetterWithResourceIdentity: {
      deadLetterDestination: {
        endpointType: 'StorageBlob'
        properties: {
          blobContainerName: 'event-grid-deadletter'
          resourceId: storage.id
        }
      }
      identity: {
        type: 'UserAssigned'
        userAssignedIdentity: eventGridIdentityId
      }
    }
    destination: {
      endpointType: 'AzureFunction'
      properties: {
        maxEventsPerBatch: 1
        preferredBatchSizeInKilobytes: 64
        resourceId: '${functionApp.id}/functions/aml_event_handler'
      }
    }
    eventDeliverySchema: 'EventGridSchema'
    filter: {
      enableAdvancedFilteringOnArrays: true
      advancedFilters: [
        {
          key: 'data.RunTags.azureml_modelmonitor_threshold_breached'
          operatorType: 'StringContains'
          values: [
            'has failed due to one or more features violating metric thresholds'
          ]
        }
      ]
      includedEventTypes: [
        'Microsoft.MachineLearningServices.RunStatusChanged'
      ]
      isSubjectCaseSensitive: false
    }
    retryPolicy: {
      eventTimeToLiveInMinutes: 1440
      maxDeliveryAttempts: 12
    }
  }
}

output eventSubscriptionId string = amlMonitorEvents.id
output systemTopicId string = amlSystemTopic.id
