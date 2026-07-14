# Incremental Azure MLOps Roadmap

This repository is organized as a minimum working POC followed by capability phases. The ordering uses Microsoft's five-level MLOps maturity model as a guide, not as a claim that a repository alone changes organizational maturity. Teams can exhibit capabilities from several levels at once. [S1]

**Current verified status:** Level 2-aligned reference POC. The repository implements Level 3/4 capability templates, but those phases remain aspirational until their live Azure/Snowflake exit evidence below is collected. Static SDK/Bicep validation and credential-free tests do not establish tenant, release-environment, monitoring-delivery, or organizational maturity.

## Minimum POC: reproducible lifecycle

**Guide alignment:** Level 2 automated training, plus one controlled batch release path needed to prove the Snowflake output boundary.

**Included capability**

- version-controlled Python, component YAML, environment, and data contracts;
- managed AML compute and component pipeline;
- immutable Snowflake pulls into AML job artifacts;
- point-in-time feature/label construction;
- centralized MLflow metrics and versioned model registration;
- explicit candidate-versus-champion promotion decision;
- explicit batch deployment invocation;
- all-or-nothing Snowflake prediction publication;
- deterministic local acceptance scenarios and behavior tests.

**Exit evidence**

1. Unit/contract tests pass without credentials.
2. The five-scenario demo produces the expected terminal contracts twice.
3. AML component, pipeline, and environment YAML load through the pinned SDK.
4. A live operator can trace one Snowflake source batch to one AML model version and one complete Snowflake output batch.

The minimum POC deliberately keeps release initiation operator-controlled. Microsoft describes Level 2 releases as manual but easy to implement. [S1]

## Phase A: complete Level 2 platform capabilities

**Goal:** make training repeatable, managed, and event-aware.

**Repository surfaces**

- `azureml/environments/`: pinned AML runtime.
- `feature_store/`: version-controlled entity and feature-set definitions.
- `infra/main.bicep`: AML workspace, compute, shared dependencies, managed Feature Store workspace, identity-based system datastores, and least-privilege job identity.
- `src/azureml_snowflake_poc/components/train.py`: content-derived candidate versions and MLflow run provenance.

**Activation sequence**

1. Deploy the AML and Feature Store workspaces.
2. Pull the first Snowflake snapshot into AML storage.
3. Generate the feature-set specification against that AML Parquet URI.
4. Register the entity and feature set.
5. Keep offline materialization disabled until an ADLS Gen2 offline store, connection, materialization identity, and RBAC are explicitly configured.

This corresponds to the guide's managed training, centralized tracking, model management, managed environments, managed feature store, and lifecycle-event capabilities. [S1][S5][S6]

## Phase B: Level 3 automated model deployment

**Goal:** turn a passing model policy decision into a repeatable deployment while preserving exact lineage.

**Repository surfaces**

- `src/azureml_snowflake_poc/aml_gateway.py`: model registration, champion comparison, exact version deployment, and optimistic endpoint update protection.
- `azureml/scoring/batch_driver.py`: model-signature and model-metadata driven scoring schema.
- `src/azureml_snowflake_poc/components/publish.py`: batch reconciliation and selected-model provenance.
- `.github/workflows/validate.yml`: tests, SDK YAML validation, Bicep compilation, and secret/placeholders checks.

**Exit evidence**

1. Candidate registration includes MLflow run, training snapshot digest, mapping version, and metrics.
2. A mapping-version mismatch halts before inference.
3. The exact selected deployment is invoked; output is reconciled against every expected correlation key.
4. Replaying publication updates stable prediction IDs and does not duplicate rows.
5. CI validates every pull request.

The guide's full Level 3 target also includes promoted artifacts across workspaces and automated release environments. This POC uses one workspace; multi-workspace registry promotion is an explicit production extension, not a hidden claim. [S1][S3]

## Phase C: Level 4 monitored operations

**Goal:** close the production feedback loop without creating an unsafe retraining loop.

**Repository surfaces**

- `azureml/monitoring/model-monitor.schedule.yml`: input drift, prediction drift, and delayed-label performance.
- `scripts/configure_monitor.py`: exact AML output asset registration and schedule rendering.
- `infra/event-grid.bicep`: AML system topic, v2 monitor-breach filter, Function destination, retry, and dead-letter delivery.
- `functions/function_app.py` and `src/azureml_snowflake_poc/events.py`: authoritative AML state recheck and deterministic retraining job identity.

**Exit evidence**

1. Prediction and actual assets join on the same business-provided correlation ID.
2. Monitor threshold failures emit `RunStatusChanged` and reach the Function.
3. Duplicate Event Grid deliveries resolve to one retraining job name.
4. Auto-retraining remains disabled by default.
5. Enabling retraining requires an explicit source batch; the event time becomes the source cutoff.
6. Failed delivery reaches the dead-letter container and remains diagnosable in Application Insights.

Microsoft's Level 4 includes automatic retraining, feature freshness monitoring, centralized production metrics, and policy-based promotion. The POC implements the control contracts and a guarded opt-in; automatic production release after retraining remains blocked by the same promotion policy. [S1][S7][S8]

## Production extensions not claimed by this POC

- private endpoints, private DNS, and egress control;
- dev/test/prod workspaces and cross-workspace registry promotion;
- automatic rollback based on post-deployment signals;
- online feature serving or online endpoints;
- organization-specific approval, incident, retention, and cost policy;
- proven target-region availability, quota, or Snowflake tenant claims.

## Works Cited

- **[S1]** Microsoft, [MLOps maturity model](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/mlops-maturity-model).
- **[S3]** Microsoft, [Manage MLflow models in Azure Machine Learning](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-manage-models-mlflow?view=azureml-api-2).
- **[S5]** Microsoft, [What is managed feature store?](https://learn.microsoft.com/en-us/azure/machine-learning/concept-what-is-managed-feature-store?view=azureml-api-2).
- **[S6]** Microsoft, [Feature-set materialization concepts](https://learn.microsoft.com/en-us/azure/machine-learning/feature-set-materialization-concepts?view=azureml-api-2).
- **[S7]** Microsoft, [Monitor model performance in production](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-monitor-model-performance?view=azureml-api-2).
- **[S8]** Microsoft, [Azure Machine Learning Event Grid schema](https://learn.microsoft.com/en-us/azure/event-grid/event-schema-machine-learning).
