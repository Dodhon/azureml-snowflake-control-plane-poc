targetScope = 'resourceGroup'

@description('Azure region for all resources.')
param location string = resourceGroup().location

@minLength(2)
@maxLength(12)
@description('Lowercase workload prefix, for example amlcp.')
param prefix string

@allowed([
  'Enabled'
])
@description('The public-network POC supports Enabled only. Add private endpoints and DNS before disabling access.')
param publicNetworkAccess string = 'Enabled'

@description('Object ID of the deployment operator who needs Key Vault administration. Empty omits the assignment.')
param deploymentOperatorObjectId string = ''
@description('Submit one idempotent retraining job after an AML model-monitor threshold breach.')
param retrainOnMonitorBreach bool = false

@description('Business source batch to use for event-triggered retraining. Required when retrainOnMonitorBreach is true.')
param retrainingSourceBatchId string = ''


var token = toLower(uniqueString(subscription().id, resourceGroup().id, prefix))
var storageName = take('${prefix}${token}', 24)
var keyVaultName = take('${prefix}-kv-${token}', 24)
var registryName = take('acr${token}', 50)
var workspaceName = take('${prefix}-aml-${token}', 32)
var featureStoreName = take('${prefix}-features-${token}', 32)
var functionName = take('${prefix}-events-${token}', 60)
var planName = '${prefix}-events-plan'
var logName = '${prefix}-logs'
var insightsName = '${prefix}-insights'

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logName
  location: location
  properties: {
    retentionInDays: 30
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
  }
}

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: insightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
  }
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    minimumTlsVersion: 'TLS1_2'
    publicNetworkAccess: publicNetworkAccess
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
  properties: {
    deleteRetentionPolicy: {
      enabled: true
      days: 14
    }
    containerDeleteRetentionPolicy: {
      enabled: true
      days: 14
    }
  }
}

resource deadLetters 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'event-grid-deadletter'
  properties: {
    publicAccess: 'None'
  }
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    enableRbacAuthorization: true
    enablePurgeProtection: true
    enableSoftDelete: true
    publicNetworkAccess: publicNetworkAccess
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: subscription().tenantId
  }
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: registryName
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: publicNetworkAccess
  }
}

resource workspace 'Microsoft.MachineLearningServices/workspaces@2025-09-01' = {
  name: workspaceName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    applicationInsights: insights.id
    containerRegistry: registry.id
    description: 'Azure ML control plane with Snowflake data boundaries'
    friendlyName: 'Azure ML Snowflake control-plane POC'
    hbiWorkspace: true
    keyVault: keyVault.id
    publicNetworkAccess: publicNetworkAccess
    storageAccount: storage.id
    systemDatastoresAuthMode: 'Identity'
  }
}
resource featureStore 'Microsoft.MachineLearningServices/workspaces@2025-09-01' = {
  name: featureStoreName
  location: location
  kind: 'FeatureStore'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    applicationInsights: insights.id
    containerRegistry: registry.id
    description: 'Managed offline feature registry for the Azure ML control plane'
    featureStoreSettings: {
      computeRuntime: {
        sparkRuntimeVersion: '3.4'
      }
    }
    friendlyName: 'Exact quantity managed feature store'
    hbiWorkspace: true
    keyVault: keyVault.id
    publicNetworkAccess: publicNetworkAccess
    storageAccount: storage.id
    systemDatastoresAuthMode: 'Identity'
  }
}


resource cpuCluster 'Microsoft.MachineLearningServices/workspaces/computes@2024-10-01' = {
  parent: workspace
  name: 'aml-cpu-cluster'
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    computeType: 'AmlCompute'
    disableLocalAuth: true
    properties: {
      osType: 'Linux'
      remoteLoginPortPublicAccess: 'Disabled'
      scaleSettings: {
        maxNodeCount: 2
        minNodeCount: 0
        nodeIdleTimeBeforeScaleDown: 'PT120S'
      }
      vmPriority: 'Dedicated'
      vmSize: 'STANDARD_DS3_V2'
    }
  }
}

resource functionPlan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: planName
  location: location
  kind: 'linux'
  sku: {
    name: 'Y1'
    tier: 'Dynamic'
  }
  properties: {
    reserved: true
  }
}

resource functionApp 'Microsoft.Web/sites@2024-04-01' = {
  name: functionName
  location: location
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    httpsOnly: true
    publicNetworkAccess: publicNetworkAccess
    serverFarmId: functionPlan.id
    siteConfig: {
      ftpsState: 'Disabled'
      linuxFxVersion: 'Python|3.12'
      minTlsVersion: '1.2'
      appSettings: [
        {
          name: 'FUNCTIONS_EXTENSION_VERSION'
          value: '~4'
        }
        {
          name: 'FUNCTIONS_WORKER_RUNTIME'
          value: 'python'
        }
        {
          name: 'SCM_DO_BUILD_DURING_DEPLOYMENT'
          value: 'true'
        }
        {
          name: 'ENABLE_ORYX_BUILD'
          value: 'true'
        }
        {
          name: 'AZURE_TOKEN_CREDENTIALS'
          value: 'ManagedIdentityCredential'
        }
        {
          name: 'AzureWebJobsStorage__accountName'
          value: storage.name
        }
        {
          name: 'AZURE_SUBSCRIPTION_ID'
          value: subscription().subscriptionId
        }
        {
          name: 'AZURE_RESOURCE_GROUP'
          value: resourceGroup().name
        }
        {
          name: 'AZUREML_WORKSPACE_NAME'
          value: workspace.name
        }
        {
          name: 'RETRAINING_PIPELINE_PATH'
          value: 'azureml/pipelines/lifecycle.pipeline.yml'
        }
        {
          name: 'RETRAIN_ON_MONITOR_BREACH'
          value: string(retrainOnMonitorBreach)
        }
        {
          name: 'RETRAIN_SOURCE_BATCH_ID'
          value: retrainingSourceBatchId
        }
        {
          name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
          value: insights.properties.ConnectionString
        }
      ]
    }
  }
}

resource eventGridIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${prefix}-event-grid-identity'
  location: location
}

var amlDataScientistRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'f1a07417-d97a-45cb-824c-7a7467783830')
var keyVaultSecretsUserRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
var keyVaultAdministratorRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '00482a5a-887f-4fb3-b363-3b7fe8e74483')
var storageBlobDataOwnerRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b')
var storageQueueDataContributorRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '974c5e8b-45b9-4653-ba55-5f855dd0fb88')
var storageTableDataContributorRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3')
var storageBlobDataContributorRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
var acrPullRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')

resource eventGridDeadLetterRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(deadLetters.id, eventGridIdentity.id, storageBlobDataContributorRole)
  scope: deadLetters
  properties: {
    principalId: eventGridIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: storageBlobDataContributorRole
  }
}


resource functionStorageBlobRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, functionApp.id, storageBlobDataOwnerRole)
  scope: storage
  properties: {
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: storageBlobDataOwnerRole
  }
}

resource functionStorageQueueRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, functionApp.id, storageQueueDataContributorRole)
  scope: storage
  properties: {
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: storageQueueDataContributorRole
  }
}

resource functionStorageTableRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, functionApp.id, storageTableDataContributorRole)
  scope: storage
  properties: {
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: storageTableDataContributorRole
  }
}

resource functionAmlRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(workspace.id, functionApp.id, amlDataScientistRole)
  scope: workspace
  properties: {
    principalId: functionApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: amlDataScientistRole
  }
}

resource workspaceFeatureStoreRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(featureStore.id, workspace.id, amlDataScientistRole)
  scope: featureStore
  properties: {
    principalId: workspace.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: amlDataScientistRole
  }
}

resource workspaceSecretRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, workspace.id, keyVaultSecretsUserRole)
  scope: keyVault
  properties: {
    principalId: workspace.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: keyVaultSecretsUserRole
  }
}

resource workspaceStorageRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, workspace.id, storageBlobDataContributorRole)
  scope: storage
  properties: {
    principalId: workspace.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: storageBlobDataContributorRole
  }
}

resource workspaceRegistryRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, workspace.id, acrPullRole)
  scope: registry
  properties: {
    principalId: workspace.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: acrPullRole
  }
}

resource featureStoreStorageRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, featureStore.id, storageBlobDataContributorRole)
  scope: storage
  properties: {
    principalId: featureStore.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: storageBlobDataContributorRole
  }
}

resource featureStoreRegistryRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, featureStore.id, acrPullRole)
  scope: registry
  properties: {
    principalId: featureStore.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: acrPullRole
  }
}

resource featureStoreSecretRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, featureStore.id, keyVaultSecretsUserRole)
  scope: keyVault
  properties: {
    principalId: featureStore.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: keyVaultSecretsUserRole
  }
}

resource computeStorageRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, cpuCluster.id, storageBlobDataContributorRole)
  scope: storage
  properties: {
    principalId: cpuCluster.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: storageBlobDataContributorRole
  }
}

resource computeSecretRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, cpuCluster.id, keyVaultSecretsUserRole)
  scope: keyVault
  properties: {
    principalId: cpuCluster.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: keyVaultSecretsUserRole
  }
}

resource computeFeatureStoreRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(featureStore.id, cpuCluster.id, amlDataScientistRole)
  scope: featureStore
  properties: {
    principalId: cpuCluster.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: amlDataScientistRole
  }
}

resource operatorVaultRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deploymentOperatorObjectId)) {
  name: guid(keyVault.id, deploymentOperatorObjectId, keyVaultAdministratorRole)
  scope: keyVault
  properties: {
    principalId: deploymentOperatorObjectId
    principalType: 'User'
    roleDefinitionId: keyVaultAdministratorRole
  }
}

output workspaceName string = workspace.name
output workspaceId string = workspace.id
output functionAppName string = functionApp.name
output functionAppId string = functionApp.id
output keyVaultName string = keyVault.name
output storageAccountName string = storage.name
output deadLetterContainerId string = deadLetters.id
output eventGridIdentityId string = eventGridIdentity.id
output featureStoreName string = featureStore.name
