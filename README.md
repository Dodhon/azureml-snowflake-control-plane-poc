# Azure ML + Snowflake Control-Plane POC

A public, use-case-neutral reference implementation for running an event-driven MLOps lifecycle in Azure Machine Learning while keeping Snowflake as the source and business-facing prediction store.

The POC mirrors the contract discipline of the Snowflake-native control-plane POC, but changes the execution owner:

- **Snowflake owns:** source views, delayed actuals, and the durable `AML_PREDICTIONS` output table.
- **Azure ML owns:** feature engineering, managed Feature Store assets, training, MLflow model versions, promotion policy, batch endpoints, pipeline orchestration, monitoring, and evidence artifacts.
- **Azure Event Grid + Functions own:** filtered monitor-breach delivery, authoritative state rechecks, idempotent optional retraining, retry, and dead-letter handling.

No credentials or production identifiers are committed. `CHANGE_ME_*` values are deliberate deployment-time inputs.

## Core model: three planes

```text
SNOWFLAKE DATA PLANE
source views ──read-only pull──▶ AML pipeline ──transactional MERGE──▶ AML_PREDICTIONS
                                      │
                                      ▼
AZURE ML CONTROL PLANE
components → features → MLflow run/model → promotion gate → batch endpoint → monitor
                                      │
                                      ▼
AZURE EVIDENCE PLANE
AML jobs/assets/tags + monitor runs + Event Grid delivery + App Insights + dead letters
```

## Implemented lifecycle

1. **Pull immutable snapshots** from parameterized Snowflake queries with a structured query tag.
2. **Validate the exact-quantity contract:** each finite, non-negative whole-number quantity is one class; the mapping version is explicit.
3. **Build predictor-only feature data** and a point-in-time training spine inside an AML command component.
4. **Train and log** a deterministic scikit-learn candidate as an MLflow model.
5. **Register every candidate** in the AML model registry with metrics and provenance tags.
6. **Promote, retain, or halt** using complete threshold and champion-comparison evidence. Missing metrics halt.
7. **Deploy the selected exact model version** to an AML batch endpoint and invoke that deployment explicitly.
8. **Publish complete predictions** to Snowflake in one transaction using a stable prediction ID and `MERGE` retry semantics.
9. **Prepare and register monitor data assets** for input drift, prediction drift, and delayed-label model performance.
10. **Route monitor breaches through Event Grid** using only `RunStatusChanged` events with the v2 threshold-breach tag filter. The Function rechecks AML state and auto-retraining is disabled by default.

## Safety properties

| Boundary | Property |
|---|---|
| Labels | Scoring rows cannot contain target/actual columns. |
| Point-in-time join | A label only sees the latest feature row at or before label time and inside the configured tolerance. |
| Promotion | One absent, invalid, or failed metric rule prevents promotion. |
| Promotion concurrency | A managed-identity Blob lease serializes champion selection and endpoint-default mutation across AML runs. |
| Deployment | Batch invocation names the selected deployment; it does not depend on an endpoint default changing later. |
| Publication | A failed load or merge rolls back; retries update the same stable prediction IDs. |
| Events | Event Grid is at-least-once; deterministic retraining job names make handling idempotent after AML state recheck. |
| Automation | Monitor breaches log evidence by default; retraining requires an explicit setting change. |

## Repository map

```text
azureml/components/        AML command component contracts
azureml/pipelines/         lifecycle pipeline job
azureml/environments/      pinned reproducible runtime
azureml/scoring/           batch endpoint scoring driver
azureml/monitoring/        monitor schedule template
feature_store/             managed Feature Store entity/feature-set templates
functions/                 Event Grid Azure Function
infra/                     Bicep for AML, Feature Store, identities, Function, and Event Grid
snowflake/                 prediction-table and grant contract
src/azureml_snowflake_poc/ policy, cloud adapters, and repository validation
scripts/                   Function packaging and monitor configuration
tests/                     behavior-level contract tests
docs/                      architecture, roadmap, runbook, configuration, and sources
```

## Local deterministic proof

Requires Python 3.12. No Azure or Snowflake credentials are needed.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[all]'
.venv/bin/python -m pytest -q
.venv/bin/python -m azureml_snowflake_poc.demo --scenario all --output .validation/demo.json
.venv/bin/aml-poc-validate
```

The demo exposes five terminal policy paths; the test suite also checks deterministic replay:

- candidate promoted and predictions published;
- invalid exact-quantity label blocked before training;
- weak candidate retained behind the champion;
- drift breach recorded without automatic retraining;
- technical publication failure leaves no partial prediction batch.

## Real Azure/Snowflake run

A live deployment requires Azure and Snowflake administration. The operator must:

1. deploy `infra/main.bicep`;
2. configure Snowflake External OAuth for the AML compute identity, or store a key pair in Key Vault;
3. replace `CHANGE_ME_*` values in `config/poc.yaml` and apply `snowflake/001_prediction_contract.sql`;
4. register the AML environment and submit `azureml/pipelines/lifecycle.pipeline.yml`;
5. generate/register the managed feature-set specification after the first AML Parquet snapshot exists;
6. render and create the model-monitor schedule;
7. package/deploy the Function, then deploy `infra/event-grid.bicep`.

Exact commands, pass conditions, failure triage, and rollback steps are in [docs/operations.md](docs/operations.md).

## Deliberate limits

This repository is a deployable reference, not a production guarantee. Before production use, verify target-region support and quotas, private endpoint/DNS design, Snowflake External OAuth claims, organizational RBAC, retention, cost limits, and incident routing. The default Bicep permits public network access for a demonstrable POC; private networking is a separate deployment decision.

The currently verified maturity is Level 2-aligned. Level 3/4 surfaces are implemented as activation templates but remain aspirational until the live exit evidence in [docs/maturity-roadmap.md](docs/maturity-roadmap.md) is collected.

Managed Feature Store and model-performance monitoring capabilities can be region- or preview-dependent. The pipeline remains fully AML-executed even when those optional managed surfaces are unavailable: it builds versioned AML data artifacts, performs its own point-in-time join, and preserves the same feature/version evidence.

## Documentation

- [Architecture and contracts](docs/architecture.md)
- [Incremental Azure MLOps maturity roadmap](docs/maturity-roadmap.md)
- [Configuration and placeholders](docs/configuration.md)
- [Build, deploy, operate, and recover](docs/operations.md)
- [Official source index](docs/sources.md)

## License

MIT
