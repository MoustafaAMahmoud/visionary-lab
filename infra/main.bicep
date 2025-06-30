// File: infra/main.bicep

// This Bicep template deploys an Azure Container App Environment and two Container Apps (backend and frontend) for the Visionary Lab project
// It also creates an Azure Storage Account and a Log Analytics workspace for monitoring and logging
// The backend container app is configured to use the Azure Blob Storage account and OpenAI deployments for LLM and image generation
// The frontend container app is configured to use the Azure Blob Storage account and OpenAI deployments for LLM and image generation

@description('Location for all resources')
param location string = resourceGroup().location

// Parameters for the Container App Environment and Container Apps
@description('Name of the Container App Environment')
param containerAppEnvName string = 'visionary-lab-container-env'
@description('Name of the Container App')
param containerAppNameBackend string = 'visionary-lab-backend'
param containerAppNameFrontend string = 'visionary-lab-frontend'
// Parameters for the Log Analytics workspace
param logAnalyticsWorkspaceName string = 'visionary-lab-log-analytics-workspace'

// Parameters for the Azure Storage Account
@description('Unique name for the Storage Account (3-24 lowercase letters and numbers)')
param storageAccountName string = 'a${toLower(uniqueString(resourceGroup().id, 'storage'))}'

// Parameters for Azure Cosmos DB
@description('Unique name for the Cosmos DB account (3-50 lowercase letters, numbers, and hyphens)')
param cosmosAccountName string = 'cosmos-${toLower(uniqueString(resourceGroup().id, 'cosmos'))}'
@description('Name of the Cosmos DB database')
param cosmosDatabaseName string = 'visionarylab'
@description('Name of the Cosmos DB container')
param cosmosContainerName string = 'metadata'

// Parameters for the OpenAI deployments
@description('Name of the Azure OpenAI account')
param llmOpenAiAccountName string = 'myOpenAiAccount'
param llmDeploymentName string = 'gpt-4o-2'
param llmModelType string = 'gpt-4o'
param imageGenOpenAiAccountName string = 'myOpenAiAccount'
param imageGenDeploymentName string = 'gpt-image-1'
param imageGenModelType string = 'gpt-image-1'
param soraOpenAiAccountName string = 'myOpenAiAccount'
param soraDeploymentName string = 'sora'
@secure()
param IMAGEGEN_AOAI_API_KEY string
@secure()
param LLM_AOAI_API_KEY string
@secure()
param SORA_AOAI_API_KEY string


// Parameters for the Docker images for the backend and frontend container apps
param DOCKER_IMAGE_BACKEND string = 'aigbbemea.azurecr.io/visionarylab-video:latest'
param DOCKER_IMAGE_FRONTEND string = 'aigbbemea.azurecr.io/visionarylab-frontend-video:latest'
param API_PROTOCOL string = ''
param API_HOSTNAME string = ''
param API_PORT string = ''

// Azure Storage Account
module storageAccountMod './modules/storageAccount.bicep' = {
  name: 'storageAccountMod'
  params: {
    location: location
    storageAccountName: storageAccountName
    // keyVaultName: keyVaultMod.outputs.keyVaultName
    deployNew: true  // set false to reuse an existing storage account
  }
}

// Azure Storage Account Container for Images
module storageContainerImagesMod './modules/storageAccountContainer.bicep' = {
  name: 'storageContainerImagesMod'
  params: {
    storageAccountName: storageAccountName
    containerName: 'images'
    deployNew: true  // set false to reuse an existing container
  }
  dependsOn: [
    storageAccountMod
  ]
}

// Azure Storage Account Container for Videos
module storageContainerVideosMod './modules/storageAccountContainer.bicep' = {
  name: 'storageContainerVideosMod'
  params: {
    storageAccountName: storageAccountName
    containerName: 'videos'
    deployNew: true  // set false to reuse an existing container
  }
  dependsOn: [
    storageAccountMod
  ]
}

// Azure Cosmos DB
// This module creates a Cosmos DB account with serverless pricing for metadata storage
module cosmosDbMod './modules/cosmosDb.bicep' = {
  name: 'cosmosDbMod'
  params: {
    location: location
    cosmosAccountName: cosmosAccountName
    databaseName: cosmosDatabaseName
    containerName: cosmosContainerName
    partitionKey: '/media_type'
    deployNew: true  // set false to reuse an existing Cosmos DB account
  }
}

// OpenAI deployment module for LLM
// This module creates an OpenAI deployment for the LLM model
module llmOpenAiAccount './modules/openAiDeployment.bicep' = {
  name: 'llmOpenAiAccount'
  params: {
    openAiAccountName: llmOpenAiAccountName
    DeploymentName: llmDeploymentName
    ModelType: llmModelType
    ModelVersion: '2024-11-20'
    location: location
    deployNew: false  // set false to reuse an existing deployment
  }
  dependsOn: [
    // keyVaultMod
    storageAccountMod
  ]
}

// OpenAI deployment for Image Generation
// This module creates an OpenAI deployment for the image generation models
module imageGenOpenAiAccount './modules/openAiDeployment.bicep' = {
  name: 'imageGenOpenAiAccount'
  params: {
    openAiAccountName: imageGenOpenAiAccountName
    DeploymentName: imageGenDeploymentName
    ModelType: imageGenModelType
    ModelVersion: '2024-11-20'
    location: location
    deployNew: false  // set false to reuse an existing deployment
  }
  dependsOn: [
    storageAccountMod
  ]
}

// Azure Container App Environment
// This module creates a container app environment for the backend and frontend container apps
// It also creates a Log Analytics workspace for monitoring and logging
// The Log Analytics workspace is linked to the container app environment
module containerAppEnvMod './modules/containerAppEnv.bicep' = {
  name: 'containerAppEnvMod'
  params: {
    location: location
    containerAppEnvName: containerAppEnvName
    logAnalyticsWorkspaceName: logAnalyticsWorkspaceName
    deployNew: true  // set false to reuse an existing environment
  }
}

// Container App for Backend
// This module creates a container app for the backend service
// It uses the container app environment created in the previous module
// The container app is configured to use Azure Blob Storage, Cosmos DB, and OpenAI deployments
module containerAppBackend './modules/containerApp.bicep' = {
  name: 'containerAppBackend'
  params: {
    location: location
    containerAppName: containerAppNameBackend
    containerAppEnvId: containerAppEnvMod.outputs.containerAppEnvId
    targetPort: 80
    deployNew: true  // set false to reuse an existing container app
    AZURE_BLOB_SERVICE_URL: storageAccountMod.outputs.storageAccountPrimaryEndpoint
    AZURE_STORAGE_ACCOUNT_KEY: storageAccountMod.outputs.storageAccountKey
    AZURE_STORAGE_ACCOUNT_NAME: storageAccountName
    AZURE_BLOB_IMAGE_CONTAINER: 'images'
    AZURE_BLOB_VIDEO_CONTAINER: 'videos'
    AZURE_COSMOS_DB_ENDPOINT: cosmosDbMod.outputs.cosmosEndpoint
    AZURE_COSMOS_DB_KEY: cosmosDbMod.outputs.cosmosPrimaryKey
    AZURE_COSMOS_DB_ID: cosmosDatabaseName
    AZURE_COSMOS_CONTAINER_ID: cosmosContainerName
    DOCKER_IMAGE: DOCKER_IMAGE_BACKEND
    IMAGEGEN_AOAI_API_KEY: IMAGEGEN_AOAI_API_KEY
    LLM_AOAI_API_KEY: LLM_AOAI_API_KEY
    SORA_AOAI_RESOURCE: soraOpenAiAccountName
    SORA_DEPLOYMENT: soraDeploymentName
    SORA_AOAI_API_KEY: SORA_AOAI_API_KEY
  }
  dependsOn: [
    storageAccountMod
    storageContainerImagesMod
    storageContainerVideosMod
    cosmosDbMod
  ]
}

// Container App for Frontend
// This module creates a container app for the frontend service
// It uses the container app environment created in the previous module
// The container app is configured to use Azure Blob Storage, Cosmos DB, and OpenAI deployments
module containerAppFrontend './modules/containerApp.bicep' = {
  name: 'containerAppFrontend'
  params: {
    location: location
    containerAppName: containerAppNameFrontend
    containerAppEnvId: containerAppEnvMod.outputs.containerAppEnvId
    targetPort: 3000
    deployNew: true  // set false to reuse an existing container app
    AZURE_BLOB_SERVICE_URL: storageAccountMod.outputs.storageAccountPrimaryEndpoint
    AZURE_STORAGE_ACCOUNT_KEY: storageAccountMod.outputs.storageAccountKey
    AZURE_STORAGE_ACCOUNT_NAME: storageAccountName
    AZURE_BLOB_IMAGE_CONTAINER: 'images'
    AZURE_BLOB_VIDEO_CONTAINER: 'videos'
    AZURE_COSMOS_DB_ENDPOINT: cosmosDbMod.outputs.cosmosEndpoint
    AZURE_COSMOS_DB_KEY: cosmosDbMod.outputs.cosmosPrimaryKey
    AZURE_COSMOS_DB_ID: cosmosDatabaseName
    AZURE_COSMOS_CONTAINER_ID: cosmosContainerName
    DOCKER_IMAGE: DOCKER_IMAGE_FRONTEND
    IMAGEGEN_AOAI_API_KEY: IMAGEGEN_AOAI_API_KEY
    LLM_AOAI_API_KEY: LLM_AOAI_API_KEY
    API_PROTOCOL: API_PROTOCOL == '' ? 'https' : API_PROTOCOL
    API_PORT: API_PORT == '' ? '443' : API_PORT
    API_HOSTNAME: API_HOSTNAME == '' ? '${containerAppNameBackend}.${containerAppEnvMod.outputs.containerAppDefaultDomain}' : API_HOSTNAME
  }
  dependsOn: [
    storageAccountMod
    storageContainerImagesMod
    storageContainerVideosMod
    cosmosDbMod
  ]
}

// Outputs
output storageAccountName string = storageAccountMod.outputs.storageAccountName
output storageAccountEndpoint string = storageAccountMod.outputs.storageAccountPrimaryEndpoint
output cosmosAccountName string = cosmosDbMod.outputs.cosmosAccountName
output cosmosEndpoint string = cosmosDbMod.outputs.cosmosEndpoint
output cosmosDatabaseName string = cosmosDbMod.outputs.databaseName
output cosmosContainerName string = cosmosDbMod.outputs.containerName
output backendAppUrl string = 'https://${containerAppBackend.outputs.containerAppFqdn}'
output frontendAppUrl string = 'https://${containerAppFrontend.outputs.containerAppFqdn}'
