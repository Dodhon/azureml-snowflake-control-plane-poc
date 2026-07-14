# Build, Deploy, Operate, and Recover

Commands use Bash syntax and placeholders such as `$RESOURCE_GROUP`; set them in the operator shell. Review every cloud and Snowflake mutation before execution. This repository does not deploy resources automatically.

## 1. Local proof before cloud work

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[all]'
.venv/bin/python -m ruff check src tests scripts functions feature_store azureml/scoring
.venv/bin/python -m pytest -q
.venv/bin/python -m azureml_snowflake_poc.demo \
  --scenario all \
  --output .validation/demo.json
.venv/bin/python scripts/load_azureml_yaml.py
.venv/bin/aml-poc-validate
```

Run the demo twice and compare `.validation/demo.json`; stable fixtures should produce the same terminal states and prediction IDs. This proves local contracts only. It does not prove Azure quotas, identity propagation, Snowflake OAuth, or live publication.

## 2. Prepare account capabilities

Required operator tools and permissions:

- Python 3.12;
- Azure CLI plus the `ml` extension;
- permission to deploy resources and role assignments in one resource group;
- permission to configure Snowflake external OAuth, user/role grants, views, and the POC output table;
- a target region with AML, managed Feature Store, Linux Consumption Functions, and `STANDARD_DS3_V2` quota.

```bash
az extension add --name ml
az provider register --namespace Microsoft.MachineLearningServices
az provider register --namespace Microsoft.EventGrid
az provider register --namespace Microsoft.Web
az provider register --namespace Microsoft.Storage
```

Provider registration and RBAC propagation are asynchronous. Confirm `registrationState` is `Registered` before deployment.

## 3. Adapt Snowflake and configuration

1. Follow [configuration.md](configuration.md).
2. Configure the Snowflake external OAuth integration and service-user mapping.
3. Review and apply `snowflake/001_prediction_contract.sql` using an administrator role.
4. Confirm the runtime role can select all three views and mutate only the POC prediction table.
5. Keep `config/poc.yaml` credential-free.

The SQL file is additive and contains no teardown. Rollback of its grants/table is an administrator-owned decision because deletion can destroy evidence.

## 4. Deploy Azure resources

```bash
export RESOURCE_GROUP='<resource-group>'
export LOCATION='<azure-region>'
export PREFIX='<2-to-12-char-lowercase-prefix>'
export DEPLOYMENT_NAME='aml-snowflake-poc'
export DEPLOYMENT_OPERATOR_OBJECT_ID="$(az ad signed-in-user show --query id -o tsv)"

az group create --name "$RESOURCE_GROUP" --location "$LOCATION"
az deployment group create \
  --name "$DEPLOYMENT_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --template-file infra/main.bicep \
  --parameters prefix="$PREFIX" location="$LOCATION" \
               deploymentOperatorObjectId="$DEPLOYMENT_OPERATOR_OBJECT_ID"

az deployment group show \
  --name "$DEPLOYMENT_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query properties.outputs \
  --output json
```

Capture these deployment outputs:

```bash
export AML_WORKSPACE='<workspaceName.value>'
export FEATURE_STORE='<featureStoreName.value>'
export FUNCTION_APP='<functionAppName.value>'
export STORAGE_ACCOUNT='<storageAccountName.value>'
export EVENT_GRID_IDENTITY_ID='<eventGridIdentityId.value>'
export PROMOTION_LOCK_BLOB_URL='<promotionLockBlobUrl.value>'
```

Set `azure.promotion_lock_blob_url` in `config/poc.yaml` to `$PROMOTION_LOCK_BLOB_URL`. Supplying `deploymentOperatorObjectId` grants the named operator Key Vault administration for initial setup; omit it only when another identity already owns vault configuration.

The POC supports public service endpoints. Do not set `publicNetworkAccess=Disabled`; the template intentionally rejects it until private endpoints and DNS are added.

## 5. Register the AML runtime

```bash
az configure --defaults group="$RESOURCE_GROUP" workspace="$AML_WORKSPACE" location="$LOCATION"
az ml environment create --file azureml/environments/runtime.environment.yml
```

Wait until the environment build is complete. The pipeline refers to `azureml:aml-snowflake-poc-runtime:1` exactly.

## 6. Submit the minimum lifecycle

Edit the non-secret target identifiers and queries in `config/poc.yaml`, then submit with a unique business source batch and immutable cutoff:

```bash
export SOURCE_BATCH_ID='<business-source-batch>'
export SOURCE_CUTOFF='<RFC3339-cutoff>'

az ml job create \
  --file azureml/pipelines/lifecycle.pipeline.yml \
  --set inputs.source_batch_id="$SOURCE_BATCH_ID" \
        inputs.source_cutoff="$SOURCE_CUTOFF" \
        inputs.source_event_id='manual'
```

The pipeline packages local component definitions and configuration. Track the returned job name:

```bash
export AML_JOB='<pipeline-job-name>'
az ml job show --name "$AML_JOB" --query '{status:status,studio:services.Studio.endpoint}'
az ml job download --name "$AML_JOB" --download-path .validation/jobs
```

A valid terminal run has:

- source manifest row counts and query hashes;
- a data decision of `PASS`;
- training result with MLflow run ID, content-derived candidate version, mapping version, and metrics;
- selection of either the candidate (`PROMOTE`) or exact champion (`RETAIN`);
- one completed batch deployment invocation;
- reconciled prediction count equal to expected scoring keys;
- `PUBLISHED` result after Snowflake commit;
- four monitor datasets and a monitor manifest.

The compute identity holds the Blob lease while model selection changes the endpoint default. If a process terminates while holding the infinite lease, inspect the failed AML job and break only the exact `promotion-locks/endpoint-default.lock` lease before retrying; breaking a live lease can reintroduce concurrent promotion.

## 7. Verify Snowflake publication

Use the batch and model provenance from `publish_result`:

```sql
SELECT
  SOURCE_BATCH_ID,
  MODEL_NAME,
  MODEL_VERSION,
  QUANTITY_CLASS_MAPPING_VERSION,
  COUNT(*) AS ROWS,
  COUNT(DISTINCT PREDICTION_ID) AS UNIQUE_PREDICTIONS,
  COUNT(DISTINCT CORRELATION_ID) AS UNIQUE_BUSINESS_EVENTS
FROM <DATABASE>.<SCHEMA>.AML_PREDICTIONS
WHERE SOURCE_BATCH_ID = '<SOURCE_BATCH_ID>'
GROUP BY 1, 2, 3, 4;
```

Re-run the same source batch only when validating idempotency. Stable identities must update without increasing the distinct prediction count.

## 8. Register the managed feature contract

Use the completed pipeline's durable `training_features_snapshot` AML path. It must resolve to Parquet files accessible to the Feature Store workspace identity.

Run specification generation on Linux or another platform supported by the pinned `azureml-featurestore` package. The macOS arm64 development extra intentionally omits that package; AML pipeline and repository validation still run there.

```bash
.venv/bin/python -m pip install -e '.[featurestore]'
.venv/bin/python feature_store/generate_spec.py \
  --source-path '<AML-PARQUET-GLOB>' \
  --output feature_store/featuresets/exact_quantity/spec

az ml feature-store-entity create \
  --file feature_store/entities/entity.yaml \
  --resource-group "$RESOURCE_GROUP" \
  --feature-store-name "$FEATURE_STORE"

az ml feature-set create \
  --file feature_store/featuresets/exact_quantity/featureset.yaml \
  --resource-group "$RESOURCE_GROUP" \
  --feature-store-name "$FEATURE_STORE"
```

The committed feature set has offline and online materialization disabled. To enable offline materialization, first provision ADLS Gen2, register an offline-store connection, assign a materialization identity, grant storage and AML permissions, and then enable the feature-set setting. Do not toggle the flag alone.

## 9. Configure model monitoring

Read the selected batch deployment from the pipeline `selection` output. The deployment name is immutable for the selected model version.

```bash
export BATCH_ENDPOINT='exact-quantity-batch'
export BATCH_DEPLOYMENT='<selected-deployment-name>'
export ALERT_EMAIL='<operator-or-team-email>'

export AZURE_SUBSCRIPTION_ID="$(az account show --query id -o tsv)"
export AZURE_RESOURCE_GROUP="$RESOURCE_GROUP"
export AZUREML_WORKSPACE_NAME="$AML_WORKSPACE"

.venv/bin/python scripts/configure_monitor.py \
  --job-name "$AML_JOB" \
  --endpoint-name "$BATCH_ENDPOINT" \
  --deployment-name "$BATCH_DEPLOYMENT" \
  --email "$ALERT_EMAIL"
```

The script always SDK-validates the rendered schedule. Normal mode requires a completed pipeline job, validates all four durable AML output paths, creates or updates their Data assets, and creates or updates the schedule. `--render-only` performs credential-free rendering and SDK validation without reading or mutating Azure. Keep the rendered file out of Git, but retain each applied job/deployment tuple as release evidence for rollback.


## 10. Deploy Function and Event Grid

The destination Function must exist before the Event Grid subscription:

```bash
.venv/bin/python scripts/package_function.py --output dist/aml-event-function.zip

az functionapp deployment source config-zip \
  --resource-group "$RESOURCE_GROUP" \
  --name "$FUNCTION_APP" \
  --src dist/aml-event-function.zip \
  --build-remote true

az deployment group create \
  --name aml-snowflake-event-grid \
  --resource-group "$RESOURCE_GROUP" \
  --template-file infra/event-grid.bicep \
  --parameters workspaceName="$AML_WORKSPACE" \
               functionAppName="$FUNCTION_APP" \
               storageAccountName="$STORAGE_ACCOUNT" \
               eventGridIdentityId="$EVENT_GRID_IDENTITY_ID"
```

Event Grid uses an AML system topic with a user-assigned delivery identity, one threshold-tag filter, 12 delivery attempts, a 24-hour TTL, and container-scoped dead-letter access.

## 11. Opt in to guarded retraining

Default behavior is log-only. To enable event-triggered retraining, redeploy the main template with both parameters:

```bash
az deployment group create \
  --name "$DEPLOYMENT_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --template-file infra/main.bicep \
  --parameters prefix="$PREFIX" location="$LOCATION" \
               retrainOnMonitorBreach=true \
               retrainingSourceBatchId='<business-source-batch>'
```

The Function still rechecks AML run status, derives one job name from the Event Grid event ID, and submits the event time as the source cutoff. The resulting pipeline must pass the ordinary promotion gate; monitor events never directly promote a model.

## 12. Failure triage

| Symptom | First evidence | Action |
|---|---|---|
| AML pull unauthorized | pull job log and Snowflake login history | verify managed identity token audience, user mapping, and role |
| Key Vault 403 | compute principal ID and role assignment | wait for RBAC propagation; verify vault scope |
| data decision `BLOCK` | `data_decision` output | repair alias/domain/point-in-time contract; submit new run |
| deployment concurrency error | selection output and endpoint default | re-read endpoint state; rerun selection against current champion |
| promotion waits on Blob lease | promotion lock blob and active AML jobs | confirm no promotion is live; break a stale lease only after the failed holder is terminal |
| missing/extra batch rows | `scoring_result` and `publish_result` | inspect batch driver schema and correlation IDs; no Snowflake write occurred |
| Snowflake write failure | AML publish log/query tag | verify grants/table schema; transaction rollback is attempted |
| monitor schedule rejected | rendered YAML and pinned SDK validation | confirm target-region monitor v2 support and current preview contract |
| Function import failure | Application Insights traces | confirm remote build completed and extension bundle v4 loaded |
| repeated Event Grid failures | system-topic delivery metrics and dead-letter container | inspect Function response/telemetry; replay only after correction |

## 13. Rollback

### Model rollback

1. Identify the last known model version and its deployment from AML registry/run evidence.
2. Confirm no promotion job is active, set `LEASE_ID` to a new GUID, and acquire the operator lease:

   ```bash
   az storage blob lease acquire \
     --account-name "$STORAGE_ACCOUNT" \
     --container-name promotion-locks \
     --blob-name endpoint-default.lock \
     --lease-duration -1 \
     --proposed-lease-id "$LEASE_ID" \
     --auth-mode login
   ```

3. Install an `EXIT` trap that releases this exact lease ID, then set the batch endpoint default back to the immutable deployment:

   ```bash
   release_promotion_lease() {
     az storage blob lease release \
       --account-name "$STORAGE_ACCOUNT" \
       --container-name promotion-locks \
       --blob-name endpoint-default.lock \
       --lease-id "$LEASE_ID" \
       --auth-mode login
   }
   trap release_promotion_lease EXIT
   az ml batch-endpoint update \
     --name "$BATCH_ENDPOINT" \
     --set defaults.deployment_name="$LAST_KNOWN_GOOD_DEPLOYMENT"
   ```

4. Run a bounded scoring batch and reconcile its output.
5. Resume Snowflake publication only after reconciliation passes.
6. Call `release_promotion_lease`, then clear the trap with `trap - EXIT`. If the operator process dies first, verify it is terminal before running:

   ```bash
   az storage blob lease break \
     --account-name "$STORAGE_ACCOUNT" \
     --container-name promotion-locks \
     --blob-name endpoint-default.lock \
     --auth-mode login
   ```

The acquire/release/break syntax and `--auth-mode login` behavior are documented in the [Azure CLI Blob lease reference](https://learn.microsoft.com/en-us/cli/azure/storage/blob/lease?view=azure-cli-latest).

Do not delete the failed model version; retain it for audit.

### Monitor rollback

1. Set `MONITOR_SCHEDULE_NAME='exact_quantity_model_monitoring'`, matching the committed schedule template, then run `az ml schedule disable --name "$MONITOR_SCHEDULE_NAME"`.
2. Re-run `scripts/configure_monitor.py` with the previous known-good completed AML job, endpoint, deployment, email, and configuration recorded in release evidence.
3. Verify the restored asset version and schedule, then run `az ml schedule enable --name "$MONITOR_SCHEDULE_NAME"`.

Disabling is the fail-closed action when prior release evidence is unavailable; do not leave a known-bad schedule enabled.

### Event automation rollback

Redeploy `infra/main.bicep` with `retrainOnMonitorBreach=false`. The monitor and Event Grid delivery remain observable, while the Function returns log-only decisions.

### Infrastructure rollback

Delete the dedicated resource group only if it contains no shared resources and evidence retention has been approved. Key Vault purge protection intentionally prevents immediate permanent purge. Remove Snowflake grants/table separately under Snowflake change control.
