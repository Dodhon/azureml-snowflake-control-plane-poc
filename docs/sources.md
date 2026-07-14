# Official Source Index

Checked 2026-07-14. Microsoft Learn, Azure schema endpoints, Azure SDK/CLI references, Snowflake documentation, and official example repositories are the authority for capability claims. Repository behavior is additionally supported by local tests; live tenant capability is not inferred from documentation alone.

## Azure Machine Learning lifecycle

| Ref | Source | Repository decision supported |
|---|---|---|
| S1 | [MLOps maturity model](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/mlops-maturity-model) | minimum POC and incremental Phase A/B/C ordering |
| S2 | [Create and run component-based pipelines](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-create-component-pipeline-cli?view=azureml-api-2) | command components, reusable pipeline graph, managed jobs |
| S3 | [Manage MLflow models](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-manage-models-mlflow?view=azureml-api-2) | MLflow model registration and versioned model lifecycle |
| S4 | [Batch endpoints](https://learn.microsoft.com/en-us/azure/machine-learning/concept-endpoints-batch?view=azureml-api-2) | asynchronous batch deployment and invocation |
| S5 | [What is managed feature store?](https://learn.microsoft.com/en-us/azure/machine-learning/concept-what-is-managed-feature-store?view=azureml-api-2) | separate Feature Store workspace, entity and feature-set assets |
| S6 | [Feature-set materialization concepts](https://learn.microsoft.com/en-us/azure/machine-learning/feature-set-materialization-concepts?view=azureml-api-2) | offline store, materialization identity, RBAC prerequisites; materialization disabled by default |
| S7 | [Monitor model performance in production](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-monitor-model-performance?view=azureml-api-2) | v2 model performance monitor assets, correlation ID join, thresholds |
| S8 | [Azure Machine Learning Event Grid schema](https://learn.microsoft.com/en-us/azure/event-grid/event-schema-machine-learning) | exact AML event names and v2 monitor failure represented by `RunStatusChanged` run tags |
| S10 | [Identity-based service authentication](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-identity-based-service-authentication?view=azureml-api-2) | managed identity and `DefaultAzureCredential` boundary |
| S11 | [Azure ML YAML reference overview](https://learn.microsoft.com/en-us/azure/machine-learning/reference-yaml-overview?view=azureml-api-2) | schema-backed component, environment, pipeline, and monitor YAML |

## Event Grid, Functions, and infrastructure

| Ref | Source | Repository decision supported |
|---|---|---|
| S12 | [Event Grid delivery with managed identity](https://learn.microsoft.com/en-us/azure/event-grid/managed-service-identity) | user-assigned identity attached to system topic and identity-based dead-letter delivery |
| S13 | [Event Grid event subscription ARM reference](https://learn.microsoft.com/en-us/azure/templates/microsoft.eventgrid/2025-02-15/eventsubscriptions) | destination, filters, retry, dead-letter-with-identity property shapes |
| S14 | [Event Grid system topic ARM reference](https://learn.microsoft.com/en-us/azure/templates/microsoft.eventgrid/2025-02-15/systemtopics) | AML source system topic and topic identity |
| S15 | [AML workspace ARM reference](https://learn.microsoft.com/en-us/azure/templates/microsoft.machinelearningservices/2025-09-01/workspaces) | Feature Store kind/settings and identity system datastore mode |
| S16 | [Azure Functions Event Grid trigger](https://learn.microsoft.com/en-us/azure/azure-functions/functions-bindings-event-grid?tabs=python-v2%2Cisolated-process%2Cnodejs-v4&pivots=programming-language-python) | Python v2 Event Grid trigger and extension registration |
| S17 | [Zip deployment for Azure Functions](https://learn.microsoft.com/en-us/azure/azure-functions/deployment-zip-push) | deterministic package plus remote dependency build |
| S18 | [Identity-based connections for Azure Functions](https://learn.microsoft.com/en-us/azure/azure-functions/functions-reference?tabs=blob&pivots=programming-language-python#connecting-to-host-storage-with-an-identity) | `AzureWebJobsStorage__accountName` and storage data-plane roles |

## Snowflake boundary

| Ref | Source | Repository decision supported |
|---|---|---|
| S9 | [External OAuth overview](https://docs.snowflake.com/en/user-guide/oauth-ext-overview) | Entra-issued OAuth access token and Snowflake security integration boundary |
| S19 | [Python connector parameters](https://docs.snowflake.com/en/developer-guide/python-connector/python-connector-api#connect) | connector OAuth/key-pair connection parameters |
| S20 | [Using pandas with the Python connector](https://docs.snowflake.com/en/developer-guide/python-connector/python-connector-pandas) | bounded DataFrame pull and `write_pandas` staging load |
| S21 | [MERGE command](https://docs.snowflake.com/en/sql-reference/sql/merge) | idempotent stable-key publication |
| S22 | [Transactions](https://docs.snowflake.com/en/sql-reference/transactions) | explicit transaction boundary and rollback behavior |

## Official implementation examples

| Source | Use |
|---|---|
| [Azure/azureml-examples](https://github.com/Azure/azureml-examples) | compared SDK v2 component, pipeline, batch endpoint, and managed Feature Store patterns |
| [Azure/azure-quickstart-templates](https://github.com/Azure/azure-quickstart-templates) | compared AML workspace dependencies and role-assignment patterns |
| [MicrosoftDocs/azure-ai-docs](https://github.com/MicrosoftDocs/azure-ai-docs) | inspected source examples and current documented monitor/event limitations |

## Evidence limits

The source set supports API shapes and intended service behavior, not target-tenant readiness. Before a production claim, collect live evidence for:

- provider registration, regional service availability, quota, and preview/API acceptance;
- Bicep deployment and role-assignment propagation;
- Snowflake security integration, token audience, user mapping, and grants;
- AML environment build, pipeline execution, exact endpoint output format, and model monitor schedule creation;
- Event Grid threshold-filter delivery, Function execution, retry, and dead-letter behavior;
- transactional Snowflake publication and idempotent replay.
