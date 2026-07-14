# Architecture and Contracts

## Objective

Run the ML lifecycle in Azure Machine Learning while retaining Snowflake as the authoritative source and business-facing prediction store. AML owns snapshot artifacts, feature construction, training, MLflow lineage, model versions, policy gates, batch deployment, monitoring, event reactions, and runtime telemetry.

## System context

```text
Snowflake                                           Azure
┌──────────────────────────┐                        ┌──────────────────────────────────────┐
│ scoring source view      │── parameterized SQL ─▶│ AML pipeline / managed compute       │
│ training feature view    │                        │  pull → feature gate → train          │
│ delayed actuals view     │                        │  → register/select → batch score      │
│                          │                        │  → monitor-data preparation           │
│ AML_PREDICTIONS          │◀─ transactional MERGE─│                                      │
└──────────────────────────┘                        │ MLflow + model registry + batch EP    │
                                                    │ AML storage + managed Feature Store   │
                                                    │ model monitor → Event Grid → Function │
                                                    └──────────────────────────────────────┘
```

Snowflake tables are never copied into an Azure analytics warehouse. A bounded query produces immutable Parquet snapshots in AML job storage; those artifacts are the evidence for one run. Predictions return to one Snowflake table only after complete-batch reconciliation.

## Lifecycle and state ownership

```text
source event / operator
        │
        ▼
PULL ──▶ BUILD FEATURES ──▶ TRAIN ──▶ REGISTER + SELECT
 │            │                │              │
 │            └─ BLOCK ────────┴─ HALT        ├─ PROMOTE candidate
 │                                             └─ RETAIN champion
 │                                                       │
 └─ source manifest                                     ▼
                                               BATCH DEPLOYMENT
                                                        │
                                                        ▼
                                           RECONCILE + SNOWFLAKE MERGE
                                                        │
                                                        ▼
                                             AML MODEL MONITOR
                                                        │
                                              threshold failure only
                                                        ▼
                                          EVENT GRID → FUNCTION
                                                        │
                                default: log only; opt-in: one retraining job
```

Ownership is explicit:

| State | Authoritative owner | Durable evidence |
|---|---|---|
| source rows and delayed labels | Snowflake | source views and source batch ID |
| run snapshot | AML job storage | Parquet artifacts plus query hashes and cutoff |
| feature contract | repository + AML Feature Store | mapping version, entity, feature-set version |
| experiment metrics | MLflow in AML | AML/MLflow run ID and metrics |
| model candidate/champion | AML model registry and batch deployment | exact model name/version, tags, endpoint deployment |
| promotion decision | repository policy executed in AML | selected model, champion comparison, reasons |
| business predictions | Snowflake | stable prediction ID, correlation ID, exact model/mapping provenance |
| production monitor state | AML model monitor | monitor run, signals, thresholds, joined correlation IDs |
| event delivery | Event Grid | event ID, retries, dead-letter blob, Function logs |

## Snowflake boundary contracts

### Input

`config/poc.yaml` contains three parameterized, read-only queries. `source_batch_id` and `source_cutoff` are bound values, not interpolated SQL. Query text must be one `SELECT`/`WITH` statement. The pull component records query hashes, row counts, source event, source batch, and cutoff.

Current scoring data contains predictors and identity only. Training labels come from the historical/delayed population. This prevents target leakage into scoring rows.

### Correlation identity

`CORRELATION_ID` is a business-provided, non-null identity shared by a prediction and its delayed actual. It is not derived from model version. Model monitor joins output to ground truth on this value. Duplicate or null correlation IDs fail monitor preparation.

`PREDICTION_ID` is separately derived from source batch, entity, correlation ID, prediction timestamp, model name/version, and mapping version. It makes Snowflake publication idempotent while preserving exact provenance.

### Output

The publisher:

1. verifies one prediction for every expected `(entity_id, feature_ts, correlation_id)` key;
2. rejects duplicates, missing rows, extras, stale mapping versions, or selected-model mismatches;
3. creates a temporary stage table in the target database and schema;
4. bulk-loads the reconciled frame;
5. performs `BEGIN` → `MERGE` on `PREDICTION_ID` → `COMMIT`;
6. attempts `ROLLBACK` on any transaction failure.

The repository proves generated SQL and reconciliation behavior locally. Live Snowflake privileges, transaction behavior, and tenant policy remain deployment evidence.

## Azure resources and identities

`infra/main.bicep` creates:

- Log Analytics and workspace-based Application Insights;
- TLS-only storage with shared-key access disabled;
- Key Vault with Azure RBAC and purge protection;
- Azure Container Registry;
- an AML workspace and autoscaling CPU cluster;
- a separate managed Feature Store workspace;
- a Linux Consumption Function App;
- a user-assigned identity for Event Grid dead-letter delivery;
- least-privilege role assignments for workspace, compute, Function, Feature Store, and Event Grid identities.

AML workspaces use identity authentication for system datastores. The compute identity reads Key Vault secrets and AML/Feature Store assets. The Function identity can read AML state and submit an idempotently named retraining job. Event Grid receives blob contributor access at the dead-letter container only.

`infra/event-grid.bicep` is intentionally separate. Deploy the Function package first so the Azure Function destination exists. It creates an AML-scoped system topic with the Event Grid user-assigned identity, then a monitor-failure subscription with retries and dead-lettering.

## Managed Feature Store boundary

The POC registers AML-engineered Parquet features in a managed Feature Store; it does not make Snowflake a Feature Store data source. `offline_enabled: false` is intentional in the committed feature set. Before enabling materialization, configure an ADLS Gen2 offline store connection, a materialization identity, and the required storage and workspace RBAC. This avoids presenting an unconfigured schedule as deployable.

The pipeline remains runnable without materialization because its feature-building component writes the versioned AML snapshot directly. Feature Store registration adds discoverability and a reusable contract in Phase A.

## Monitoring and event contract

The monitor consumes four exact pipeline outputs: model inputs, model outputs, training/validation reference data, and delayed ground truth. The renderer registers each as a versioned `mltable` asset and substitutes schedule and threshold values from `config/poc.yaml`.

Azure ML v2 model-monitor threshold failures appear as `Microsoft.MachineLearningServices.RunStatusChanged` events with a documented run-tag message. Event Grid filters that exact tag. The Function rechecks authoritative AML run status before acting. Duplicate delivery maps to the same deterministic retraining job. Auto-retraining is false unless explicitly enabled at infrastructure deployment and given a business source batch.

## Failure and rollback semantics

| Failure | Result | Recovery |
|---|---|---|
| input contract or point-in-time failure | pipeline halts before training | repair source/config; submit a new run |
| candidate below policy | champion retained | inspect metrics; no deployment rollback needed |
| endpoint changed concurrently | selection halts | re-read champion and rerun selection |
| incomplete batch output | no Snowflake publication | fix scoring/runtime; rerun same source batch |
| Snowflake write failure | transaction rollback attempted | inspect query tag/error; rerun stable IDs |
| monitor threshold breach | alert; no automatic release | triage; optional guarded retraining |
| Event Grid delivery failure | retry, then dead-letter | inspect dead-letter blob and Function telemetry |
| bad model promotion | set batch deployment default to last known model version | invoke and reconcile before new publication |

Infrastructure rollback is deployment-level or resource-group deletion. Snowflake rollback is limited to the POC table and grants in `snowflake/001_prediction_contract.sql`; the script intentionally contains no destructive teardown.
