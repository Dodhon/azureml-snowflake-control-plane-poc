# Configuration and Adaptation Contract

## Safe adaptation order

1. Copy `config/poc.yaml` outside version control if the target values are sensitive.
2. Replace account, workspace, Snowflake object, and OAuth identifiers.
3. Keep query aliases and data-contract column names aligned.
4. Apply `snowflake/001_prediction_contract.sql` after review by a Snowflake administrator.
5. Deploy Azure resources and the AML runtime environment.
6. Submit the pipeline with an explicit source batch and cutoff.
7. Render monitoring only from a completed production-like pipeline job.

Do not commit credentials, tokens, private keys, tenant-specific secrets, or rendered monitor files.

## Placeholder inventory

### Azure and Snowflake configuration

| Token | Meaning | Owner |
|---|---|---|
| `CHANGE_ME_SUBSCRIPTION_ID` | Azure subscription containing AML | Azure platform owner |
| `CHANGE_ME_RESOURCE_GROUP` | target resource group | Azure platform owner |
| `CHANGE_ME_WORKSPACE_NAME` | deployed AML workspace | Azure platform owner |
| `CHANGE_ME_FEATURE_STORE_NAME` | deployed managed Feature Store workspace | ML platform owner |
| `CHANGE_ME_ACCOUNT_IDENTIFIER` | Snowflake account identifier accepted by the connector | Snowflake administrator |
| `CHANGE_ME_SERVICE_USER` | Snowflake service user mapped to the Azure workload identity | Snowflake administrator |
| `CHANGE_ME_ML_ROLE` | least-privilege Snowflake role | Snowflake administrator |
| `CHANGE_ME_ML_WAREHOUSE` | warehouse used for bounded pull/publish queries | Snowflake administrator |
| `CHANGE_ME_DATABASE` | database containing source views and output table | data owner |
| `CHANGE_ME_SCHEMA` | schema containing source views and output table | data owner |
| `CHANGE_ME_ENTRA_SNOWFLAKE_SCOPE` | Entra application ID URI/audience configured in Snowflake external OAuth | identity owner |
| `CHANGE_ME_KEY_VAULT` | Key Vault name used only by optional key-pair authentication | Azure platform owner |

`CHANGE_ME_SOURCE_BATCH_ID` is the committed pipeline template sentinel. Override it on every operator submission; do not replace it with a permanent default.

### Generated monitor tokens

The operator does not manually edit these. `scripts/configure_monitor.py` replaces them from a completed AML job, command arguments, and `config/poc.yaml`:

- `CHANGE_ME_ENDPOINT`
- `CHANGE_ME_DEPLOYMENT`
- `CHANGE_ME_MODEL_INPUTS_ASSET`
- `CHANGE_ME_MODEL_OUTPUTS_ASSET`
- `CHANGE_ME_REFERENCE_ASSET`
- `CHANGE_ME_GROUND_TRUTH_ASSET`
- `CHANGE_ME_ASSET_VERSION`
- `CHANGE_ME_OPERATOR_EMAIL`
- `CHANGE_ME_MONITOR_FREQUENCY`
- `CHANGE_ME_MONITOR_INTERVAL`
- `CHANGE_ME_MONITOR_HOURS`
- `CHANGE_ME_MONITOR_MINUTES`
- `CHANGE_ME_DATA_DRIFT_THRESHOLD`
- `CHANGE_ME_PREDICTION_DRIFT_P_VALUE`
- `CHANGE_ME_PERFORMANCE_THRESHOLD`

The repository validator requires every committed `CHANGE_ME_*` token to be listed here.

## Snowflake authentication

### Default: Entra external OAuth

The committed configuration uses `auth_mode: external_oauth`. On AML compute, `DefaultAzureCredential` is constrained to managed identity by the runtime environment. The job requests a token for `oauth_scope`, then gives that token to the Snowflake connector. Configure Snowflake's external OAuth security integration, audience, issuer, user mapping, and role policy before running the POC. [S9]

This path stores no Snowflake password or OAuth token in the repository or AML job inputs.

### Optional: key-pair authentication

Set `auth_mode: key_pair` only if the organization requires it. Store the private key and optional passphrase in Key Vault under the configured secret names. The AML compute identity has `Key Vault Secrets User`; the deployment operator receives Key Vault Administrator only when `deploymentOperatorObjectId` is supplied. Never place private key bytes in YAML or GitHub secrets.

## Query contract

Each query must be one read-only `SELECT` or `WITH` statement. The runtime rejects semicolons and non-read prefixes. Bind parameters use Snowflake connector `pyformat` syntax:

- `%(source_batch_id)s`
- `%(source_cutoff)s`

Required aliases:

| Population | Required fields |
|---|---|
| current scoring | `ENTITY_ID`, `FEATURE_TS`, `SIGNAL_A`, `SIGNAL_B`, `SOURCE_BATCH_ID` |
| training features | `ENTITY_ID`, `FEATURE_TS`, feature columns |
| delayed actuals | `ENTITY_ID`, `EVENT_TS`, `LABEL_AVAILABLE_TS`, `ACTUAL_QUANTITY`, `CORRELATION_ID` |

`CORRELATION_ID` must be the same stable business identity available on model inputs and delayed actuals. It must not include model version. If an event can receive more than one prediction, extend the business key explicitly; do not rely on accidental row order.

## Exact-quantity label contract

The configured quantity is finite, non-negative, integral, and inside `[minimum, maximum]`. Each allowed integer is one class; no bins or ranges are inferred. `mapping_version` is carried through the feature snapshot, MLflow model tags, AML model/deployment metadata, batch output, and Snowflake publication. A mismatch halts.

## Promotion policy

Every configured metric rule is mandatory. Candidate promotion also requires a complete candidate result and a resolvable champion comparison when a champion exists. The default rules are repository examples, not empirically justified production thresholds. Change them only with a documented offline evaluation and retain the evidence with the model run.

## Monitoring configuration

The schedule uses explicit AML recurrence fields rather than an unvalidated cron string:

- `frequency`
- `interval`
- `hours`
- `minutes`

The threshold fields map one-to-one to the committed AML signals:

- `data_drift_threshold` → Jensen-Shannon distance;
- `prediction_drift_p_value` → Pearson chi-squared test;
- `performance_threshold` → classification accuracy.

Monitor assets are created from one completed pipeline job so all four inputs share an exact run-derived version.

## Azure infrastructure parameters

`infra/main.bicep` requires `prefix`. Optional parameters:

| Parameter | Default | Contract |
|---|---:|---|
| `location` | resource-group location | target region must support selected AML/Feature Store/Function resources and VM SKU |
| `publicNetworkAccess` | `Enabled` | POC supports public endpoints only; do not set Disabled without private endpoints and DNS |
| `deploymentOperatorObjectId` | empty | grants Key Vault Administrator to that user when supplied |
| `retrainOnMonitorBreach` | `false` | enables guarded Function job submission; does not bypass promotion policy |
| `retrainingSourceBatchId` | empty | required business batch when event retraining is enabled |

Event Grid deployment takes the resource names and user-assigned identity ID output by `infra/main.bicep`.

## Works Cited

- **[S9]** Snowflake, [External OAuth overview](https://docs.snowflake.com/en/user-guide/oauth-ext-overview).
- Microsoft, [Authenticate to Azure services from Azure Machine Learning](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-identity-based-service-authentication?view=azureml-api-2).
- Microsoft, [Azure Machine Learning CLI/YAML reference](https://learn.microsoft.com/en-us/azure/machine-learning/reference-yaml-overview?view=azureml-api-2).
