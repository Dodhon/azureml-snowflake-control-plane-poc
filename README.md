# Azure ML + Snowflake Control-Plane POC

Minimum working reference for a Snowflake-input/Snowflake-output machine-learning lifecycle executed in Azure Machine Learning.

## Minimum lifecycle

```text
Snowflake read-only views
        │
        ▼
AML pull → point-in-time features → MLflow train/register
        → explicit promotion gate → exact batch deployment
        → complete-batch reconciliation → transactional Snowflake MERGE
```

Snowflake remains the source and business-facing prediction store. AML owns orchestration, feature construction, experiment evidence, model versions, selection, and batch scoring. The implementation carries an explicit exact-quantity mapping version and fails closed on target leakage, incomplete metrics, concurrent deployment changes, missing predictions, or publication errors.

## Local deterministic proof

Requires Python 3.12. No cloud credentials are needed.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest -q
.venv/bin/python -m azureml_snowflake_poc.demo \
  --scenario all \
  --output .validation/demo.json
```

## Minimum cloud assets

- `azureml/components/`: pull, feature, train, register/select, batch invoke, and publish contracts.
- `azureml/pipelines/lifecycle.pipeline.yml`: one component-based AML lifecycle.
- `azureml/environments/`: pinned AML runtime.
- `azureml/scoring/`: metadata-driven batch scoring driver.
- `config/poc.yaml`: credential-free data, policy, and Snowflake boundary configuration.
- `snowflake/001_prediction_contract.sql`: additive output-table and least-privilege grant contract.
- `src/azureml_snowflake_poc/`: dependency-light domain contracts and cloud adapters.
- `tests/`: behavior-level contract evidence.

## Evidence limits

This checkpoint proves the lifecycle and local contracts. It does not yet include Azure infrastructure, managed Feature Store registration, model monitoring, Event Grid reactions, Function packaging, or an operator runbook. Live Azure/Snowflake behavior requires target-tenant validation.

## License

MIT
