# Azure ML + Snowflake Control-Plane POC

Plan level: L2
Status: ready-for-execution
Working branch: `feature/azureml-snowflake-poc`
Merge target: `main`
PR URL: pending repository publication
Merge commit: pending
Domains: MLOps platform architecture, Azure Machine Learning, Snowflake integration, event-driven operations
Skill hooks: `$mlops-platform-architecture`, `$planning`, `$planning-phase`, `$planning-affected-systems`, `$planning-edge-cases`, `$planning-validation-contract`, `$tdd`, `$github-cli-workflow`, `$writing`
Hook rationale: the request creates a public, hybrid Snowflake/Azure ML platform POC with durable data, model, event, identity, monitoring, and publication contracts.

## Executive Summary

Build and publish a use-case-neutral Azure Machine Learning equivalent of `Dodhon/snowflake-mlops-control-plane-poc`. Snowflake remains authoritative only for source features, delayed/historical actuals, and the delivered `PREDICTIONS` table. Azure owns data snapshots after extraction, feature computation and optional managed Feature Store materialization, pipeline execution, MLflow experiments, model assets, the production batch endpoint, model monitoring, Event Grid reactions, identity, observability, and CI/CD.

The implementation intentionally does not use Azure ML Data Import or Data Connections because Microsoft schedules both preview features for retirement on 30 September 2026. An AML command component pulls Snowflake directly with External OAuth from the AML managed identity; key-pair authentication through Key Vault is the fallback. The public repository contains no credentials, tenant identifiers, account locators, production object names, or source data.

## End-User Context

Primary readers are ML/platform engineers adapting an existing exact-quantity multiclass notebook. They need an inspectable path from Snowflake tables to Azure ML lifecycle assets and back to one Snowflake prediction table, without confusing Event Grid with the workflow state machine or treating successful jobs as promotion evidence.

## Intended Operator Contract

- Operator class: dual.
- Human interface: repository guide, configuration examples, Azure CLI/GitHub Actions deployment, AML Studio evidence.
- Agent subtype: CLI/shell and data-pipeline agents.
- Machine interface: YAML, Bicep, JSON gate artifacts, deterministic Python commands, structured Event Grid payloads.
- Output contract: exactly versioned AML assets and one durable Snowflake `PREDICTIONS` table.
- Failure/retry: stable run, event, model, deployment, and prediction identities; expected policy outcomes return structured decisions; technical failures fail; Event Grid processing is idempotent under at-least-once/out-of-order delivery.
- Role-specific validation: humans can follow the build/demo guide; agents can run validation, local fixture smoke, YAML loading, and deterministic reruns without hidden UI state.

## User/Operator Story Contract

When a Snowflake scoring window and labeled training history are ready, an ML platform engineer can run one Azure ML pipeline that extracts immutable snapshots, builds features, trains/registers a candidate, applies an explicit promotion policy, scores through the exact production batch deployment, and transactionally merges prediction rows back to Snowflake. They can then reconstruct the run from AML/MLflow/model/event/monitor evidence and safely rerun without duplicate predictions.

Entry: scheduled/manual AML pipeline submission with a stable `source_batch_id` and cutoff. Happy path: pull -> feature snapshot -> train -> register -> gate -> select deployment -> batch score -> Snowflake merge -> monitoring data asset. Exit: `PROMOTED_AND_PUBLISHED` or `RETAINED_AND_PUBLISHED`. Expected policy failures end as `HALTED`; technical failures end as failed AML jobs with no partial publication. Permission failures, empty pulls, mismatched class versions, duplicate events, and endpoint invocation failures are explicit recovery states.

## Functional Requirements

- R1. Pull scoring features and historical/delayed actuals from configurable Snowflake queries inside AML compute; no Azure ML Data Import/Data Connection dependency.
- R2. Keep current scoring features unlabeled; derive labels only from the separate actuals population with a point-in-time join.
- R3. Preserve exact non-negative integer quantity classes as canonical decimal strings and carry `quantity_class_mapping_version` through snapshots, experiment, model, gate, deployment, prediction, and monitoring evidence.
- R4. Persist immutable raw and feature snapshot artifacts in AML-managed Azure storage and register versioned AML data assets.
- R5. Supply a managed Feature Store adapter over landed Parquet data, including entity, versioned feature-set specification, offline materialization, and point-in-time retrieval contract; allow the minimal fixture smoke path to run without cloud materialization.
- R6. Execute reusable AML v2 command components as one pipeline: pull, validate/build features, train/evaluate, register candidate, select/deploy, invoke batch endpoint, publish Snowflake output, prepare monitoring data.
- R7. Track training with MLflow and register every successful candidate as an AML MLflow model with source/data/feature/class/code/runtime metadata.
- R8. Separate candidate registration from promotion. Use a fixed AML batch endpoint and its default deployment as production selection authority; persist the exact selected model/deployment before scoring.
- R9. Return explicit `PASS`/`BLOCK`, `PROMOTE`/`RETAIN`, and terminal run outcomes. Missing evidence is red at promotion.
- R10. Invoke the batch endpoint asynchronously, wait for terminal status, and publish only complete, schema-valid, canonical predictions.
- R11. Transactionally and idempotently merge predictions into Snowflake on stable business/provenance keys; the persistent product output is only `PREDICTIONS`.
- R12. Register production inference snapshots as AML data assets and provide AML model-monitor configuration for data drift, prediction drift, data quality, and delayed-label performance.
- R13. Route AML `RunStatusChanged`, `RunCompleted`, `ModelRegistered`, and `ModelDeployed` events through Event Grid to an Azure Function with dead-lettering. Threshold-breach retraining submission must be deduplicated by event ID and disabled by default until explicitly enabled.
- R14. Provide Bicep for AML workspace dependencies, compute, user-assigned identity, storage/dead-letter container, Key Vault, Application Insights, Function App, Event Grid subscriptions, and least-privilege role assignments.
- R15. Provide GitHub Actions CI and OIDC-based deployment templates without long-lived Azure secrets.
- R16. Mirror the Snowflake POC acceptance scenarios: best case, invalid label/feature block, weak candidate retain, drift alert, and technical failure.

## Non-Functional Requirements

- NFR1 Security: no credentials or private identifiers committed; managed identity + External OAuth is primary; Key Vault key-pair fallback is explicit; least privilege is documented.
- NFR2 Reliability: Event Grid consumers tolerate duplicates and out-of-order events; publication is transactional; endpoint/model selection is exact-versioned; retries do not duplicate rows.
- NFR3 Auditability: every output row joins to AML pipeline job, MLflow run, data asset versions, feature-set version, model version, deployment, class mapping, and source batch.
- NFR4 Reproducibility: package versions, random seed, query hash, source cutoff, code revision, feature version, and mapping version are persisted.
- NFR5 Operability: expected policy blocks do not masquerade as technical failures; technical failures remain visible in AML job status, App Insights, Azure Monitor, and Event Grid dead letters.
- NFR6 Cost: scale-to-zero CPU compute; serverless Spark only for managed Feature Store/model monitoring; no online endpoint; no always-on orchestrator.
- NFR7 Portability: model-specific functions are isolated behind typed component interfaces; public fixtures run locally without Azure or Snowflake credentials.
- NFR8 Style: Python 3.11, typed public functions, Ruff format/lint, pytest behavior tests, YAML/JSON/Bicep static validation, objective-first documentation.
- NFR9 Public safety: repository validator rejects secret-like files, private paths/identifiers, undocumented placeholders, and broken local links.

## Success Metrics

These are acceptance counts, not production SLOs:

1. All five deterministic scenarios have code-level fixture coverage and documented cloud evidence expectations.
2. A clean clone can create a virtual environment, install the package, run tests, run static validation, and execute the local fixture demo without cloud credentials.
3. Repeating the local fixture demo produces byte-equivalent decisions/prediction identities and no duplicate prediction keys.
4. All AML component/pipeline YAML files load through Azure ML SDK v2 local schema parsing where supported.
5. Bicep compiles with the standalone Bicep CLI.
6. Secret/publication scan reports zero findings.
7. The final public GitHub URL serves `main` with all validated source and documentation.

## Current Repository State

Baseline Snowflake implementation: `Dodhon/snowflake-mlops-control-plane-poc`, especially `README.md`, `docs/architecture.md`, `docs/state-machine-and-contracts.md`, `docs/snowflake-services.md`, `docs/build-and-demo.md`, and `validation/validate_repo.py`. Its current local branch has unrelated user changes and is read-only for this task.

New Azure repository baseline: isolated local repository with only `.gitignore` committed on `main`; implementation branch `feature/azureml-snowflake-poc` has no behavior yet.

## Code Style & Quality Bar References

No repo-local style guide exists yet. This plan establishes `pyproject.toml` as the style authority: Python 3.11, Ruff, pytest, type annotations at shared boundaries, small cohesive modules, no notebook-only state, no shell business logic, and behavior tests with contract comments.

## Affected Systems & Parts

| System/subsystem | Specific part | Evidence/source | Impact | Implementation | Validation | Rollback |
|---|---|---|---|---|---|---|
| Source POC | public docs/templates | local Snowflake repo | read-only baseline | map concepts only | repository mapping review | none |
| New repo | source/docs/tests/workflows | this plan | new public surface | build isolated repo | clean-clone smoke | delete/unpublish new repo |
| Snowflake | source/actual queries; `PREDICTIONS` | user contract | external read/write contract | connector + transactional merge | fixture SQL/IO contract tests; optional tenant smoke | stop jobs; drop only POC output after review |
| AML project workspace | jobs/components/assets/models | Microsoft Learn | new lifecycle plane | SDK v2/YAML | local load + cloud preflight commands | archive assets/delete POC RG |
| AML managed Feature Store | entity/feature set/materialization | Microsoft Learn | new feature plane | YAML/Python adapter | spec validation + documented cloud backfill proof | disable materialization/archive feature set |
| AML batch endpoint | endpoint/deployments/default | Microsoft Learn | production selection | exact model deployment | selection tests + documented invoke proof | reset previous default deployment |
| AML monitoring | data assets/schedule/signals | Microsoft Learn | asynchronous evidence | custom preprocessing + monitor YAML | fixture preprocessing + schema checks | disable/delete schedule |
| Event Grid | AML event subscriptions/dead letters | Microsoft Learn | at-least-once event plane | Bicep + Function | duplicate/out-of-order tests | disable subscriptions |
| Azure Function | event handler/retrain submission | Microsoft Learn | stateless dispatcher | typed event parser + idempotent AML job naming | unit tests with fake AML gateway | disable function/retraining flag |
| Azure identity/security | UAI, Key Vault, RBAC, Snowflake OAuth | Microsoft/Snowflake docs | trust boundary | Bicep + docs | static scan + deployment preflight | revoke role/security integration |
| GitHub | public repo, Actions, OIDC templates | user request | external publication | CI/deploy workflows | public clone + Actions syntax review | make private/delete repo |

## Architecture Packet Impact

This greenfield repo creates `docs/architecture.md`, `docs/state-machine-and-contracts.md`, and service/boundary guides as its architecture packet. It does not modify the Snowflake repository packet.

## Architecture/System Impact Diagram

```text
SNOWFLAKE DATA BOUNDARY                    AZURE / AML LIFECYCLE BOUNDARY

SOURCE_FEATURES ----read----+              AML pipeline job / MLflow run
ACTUALS ----------read------+----OAuth----> pull immutable snapshots
                                             |
                                             v
                                     AML data assets / ADLS
                                             |
                                  managed Feature Store (offline)
                                             |
                                             v
                          validate -> train -> register candidate
                                             |
                                      explicit model gate
                                      /              \
                                  PROMOTE           RETAIN
                                     |                 |
                          batch endpoint default    keep default
                                      \              /
                                       exact deployment
                                             |
                                      batch endpoint job
                                             |
                                      validated predictions
                                             |
PREDICTIONS <----transactional MERGE--------+
                                             |
                                   AML monitor data assets
                                             |
                                      monitor schedule
                                             |
                              Event Grid -> Azure Function
                              retry/dead-letter/idempotency
```

## Assumptions and Constraints

### User-provided

- Snowflake supplies input data.
- The delivered output table remains in Snowflake.
- Everything else should live in Azure ML/Azure services needed to support AML.
- The result must be published in a new public repository.

### Architecture assumptions

- Batch inference, not online serving, matches the table-output consumer.
- A stable `source_batch_id` or deterministic query cutoff can identify one pull.
- Snowflake External OAuth with Microsoft Entra can be configured; Key Vault-backed key pair is the fallback.
- One development environment is enough for the POC. Production multi-environment rollout is documented, not implemented.
- Source data is allowed to transit and persist in approved Azure storage for AML processing.
- The public repository demonstrates cloud-ready contracts but cannot claim tenant execution without Azure/Snowflake credentials.

### Constraints

- No paid Azure resources are provisioned in this run.
- No Snowflake objects are created or mutated in this run.
- Local workstation lacks Azure CLI, Bicep, and Terraform at discovery time; standalone temporary Bicep tooling may be used only for compile validation.
- The Azure ML Feature Store requires Parquet/ADLS-accessible source data and Spark materialization; Snowflake is not a direct feature-set source.
- Azure ML model monitoring for externally deployed/batch models requires production inference data registered as an AML data asset plus custom preprocessing.

## Feasibility Matrix

| Option | Constraint fit | Dependencies | Risks | Fallback | Validation signal | Confidence |
|---|---|---|---|---|---|---|
| AML Data Import from Snowflake | poor | retiring preview connection | stops 30 Sep 2026 | Fabric migration | retirement notice | high rejection |
| Fabric/OneLake ingestion | good long-term, violates minimal AML-only POC | Fabric capacity/pipeline | extra platform/cost | direct connector | tenant pilot | medium |
| Direct Snowflake pull in AML component | best POC fit | OAuth or key pair; network egress | connector/network ownership | Fabric later | fixture + tenant pull | high |
| Pipeline-only features | simplest | AML job storage | no shared feature catalog | managed FS adapter | local pipeline smoke | high |
| Managed Feature Store | closest Snowflake parity | separate feature-store workspace, ADLS, Spark | setup/cost/latency | pipeline-only fixture mode | registered spec/backfill | medium-high |

Decision: direct pull inside AML plus a managed Feature Store adapter. Local validation uses pipeline-only fixtures; the cloud path registers/materializes the same feature contract.

## Edge-Case, Regression Surface & Failure-Mode Review

| Edge/failure mode | Expected behavior | Treatment | Validation | Rollback/residual |
|---|---|---|---|---|
| Empty Snowflake pull | `HALTED`, no training/scoring/publish | explicit data gate | unit + fixture scenario | rerun after data readiness |
| Fractional/negative/nonfinite/out-of-domain actual | policy `BLOCK`, not technical failure | quantity contract | unit tests | correct source data |
| Mapping-version mismatch | technical failure | hard invariant | unit tests | redeploy consistent config |
| Duplicate source rows | block on key grain | validation component | unit tests | fix query/source |
| Retry after timeout | same snapshot/prediction identities; no duplicate output | deterministic IDs + MERGE | rerun smoke | inspect Snowflake transaction |
| Concurrent promotions | one endpoint update with ETag/current-state recheck | optimistic selection check | fake gateway conflict test | restore prior default deployment |
| Candidate lacks metric | `RETAIN`/unknown-is-red; first model halts | gate contract | unit tests | fix training evidence |
| Event duplicate | no duplicate retraining submission | event ID-derived job name | unit tests | dead-letter/reconcile |
| Event out of order | ignore stale/nonterminal event; query AML source of truth before action | handler re-fetch | unit tests | replay dead letter |
| Event schema casing differences | normalize documented Event Grid/CloudEvents fields | parser | event fixture tests | update parser after docs change |
| Monitor data not registered | monitor job fails visibly; scoring output remains committed | async boundary | validator/docs | restore data asset, rerun monitor |
| Endpoint invocation fails | no Snowflake publication | poll terminal state | fake gateway test | keep prior deployment, rerun |
| Snowflake MERGE fails | transaction rollback; AML job fails | staged transaction | SQL builder tests | rerun publish only |
| Credentials/network denied | technical failure, no fallback to embedded secret | explicit auth modes | config tests | fix RBAC/network |
| Azure event delivery issue | AML job/monitor remain authoritative; dead-letter + metrics | evidence plane only | docs/static config | manual reconcile |
| Regression surface | exact-quantity semantics, separate scoring/actual populations, explicit gates, exact selected version, async monitoring, one Snowflake output table remain true | parity matrix | validator + tests | block publication |

## Mental Model and Expected-Failure Manifest

Mode: batch-red.

Data flow: immutable Snowflake query snapshot -> quantity/feature validation -> deterministic features -> candidate model/metrics -> registered candidate -> explicit gate -> exact batch deployment -> prediction artifact -> transactional Snowflake merge -> registered monitoring data -> asynchronous monitor/Event Grid evidence.

Planned red tests, all predicted to fail before implementation because package modules do not yet exist:

1. Canonical quantity encoding accepts only finite, non-negative integers inside the versioned domain.
2. Scoring rows remain unlabeled while actuals alone supply training labels.
3. Missing or mismatched mapping versions raise a technical contract error.
4. Promotion is `PROMOTE` only when every required metric exists and passes; otherwise `RETAIN`.
5. First-run weak candidate halts when no production deployment exists.
6. Prediction IDs are deterministic and duplicate-free across reruns.
7. Event Grid duplicate threshold events produce the same AML retraining job identity.
8. Out-of-order/nonterminal events do not submit retraining.
9. Snowflake publication SQL uses a transaction and stable `MERGE` keys.
10. Local best/retain/block/failure demos produce the documented terminal states.

## Work Breakdown

- E1 (R1-R5): package configuration, contracts, Snowflake adapter, deterministic data/feature fixtures, Feature Store specs.
- E2 (R6-R10): AML component YAML/scripts, pipeline definition, MLflow model training, model gateway, batch endpoint deployment/invocation.
- E3 (R11): transactional Snowflake publication contract and prediction provenance.
- E4 (R12-R13): monitor preprocessing/schedule and Event Grid Function with idempotency/dead-letter posture.
- E5 (R14-R15): Bicep and GitHub Actions OIDC deployment templates.
- E6 (R16): deterministic scenario runner, tests, repository validator.
- E7: architecture, state, build/demo, security, services, and official-source documentation.
- E8: validate, secret-scan, clean-clone smoke, publish through PR, verify public main.

Provisional commit map:

1. `Add Azure ML Snowflake POC implementation`
2. `Add architecture and operator guides`
3. `Add validation and CI evidence`

Commits may be combined if each intermediate state cannot remain internally consistent.

## Validation Plan

- V1: `python -m pytest -q` — all behavior/fixture/event/publication tests pass.
- V2: `python -m ruff format --check . && python -m ruff check .` — style passes.
- V3: `python validation/validate_repo.py` — files, links, placeholders, public-safety sentinels, parity concepts, YAML/JSON structure pass.
- V4: `python scripts/run_local_demo.py --scenario all --output outputs/demo` twice, then compare manifests — five scenarios and deterministic rerun pass.
- V5: `python scripts/validate_aml_assets.py` — Azure SDK v2 loads supported component/pipeline assets without cloud calls.
- V6: `bicep build infra/main.bicep` — IaC compiles using a temporary standalone compiler.
- V7: clean temporary clone, create venv, install `.[all]`, rerun V1-V5.
- V8: secret scan across tracked files and staged diff; zero findings.
- V9: create public repository, push branches, merge validated PR, fetch public URL, verify default branch and representative files.

Preconditions: Python 3.11+, network for dependency/tool downloads, no cloud credentials required for V1-V8. V9 uses existing authenticated GitHub CLI under the user's explicit publication request.

Failure policy: any V1-V8 failure blocks publication; any V9 visibility/content mismatch blocks completion. Cloud execution is not claimed without tenant credentials and paid resource provisioning.

Acceptance artifacts: local demo manifests in ignored `outputs/`, command outputs captured in plan closeout, public repository URL/commit.

Rollback verification: before publication, delete local repo. After publication, make the new repo private or delete it; no existing repository is changed. Cloud rollback commands remain documented only because no resources are provisioned.

Old-contract speakers: the Snowflake POC's exact-quantity/class/data-plane contracts and readers expecting one `PREDICTIONS` output table. No existing Azure clients exist.

Most-likely-wrong claim: current Azure ML control-plane/event/model-monitor YAML and Bicep will deploy unchanged in an arbitrary tenant. Falsify with `az deployment group what-if`, `az ml job validate/create`, feature-store backfill, batch endpoint invocation, and Event Grid delivery in the target subscription.

## Risks and Mitigations

- Azure service drift: pin SDK/package versions, use current official schemas, and date the source index.
- Snowflake/Azure identity complexity: primary External OAuth, documented key-pair fallback, no password mode.
- Split lineage: persist AML and Snowflake IDs on every prediction row; document that cross-platform lineage is contract-based, not one native graph.
- Event Grid reliability: keep events outside the critical scoring transaction, query AML source of truth, deduplicate, dead-letter.
- Managed Feature Store cost/complexity: provide pipeline-only fixture mode and make cloud materialization an explicit capability check.
- Public leakage: generated example identifiers only, repository validator, tracked-file secret scan, clean clone.

## Top 10 Reader Questions

1. Why not Azure ML Data Import? It retires 30 September 2026.
2. Why not Fabric? It is the long-term managed ingestion alternative, but adds a separate platform beyond the requested AML-centered POC.
3. What remains in Snowflake? Source features, actuals, and the product-facing `PREDICTIONS` table.
4. Where are features owned? AML managed Feature Store in cloud; the same transform contract runs locally in fixture mode.
5. What is production model authority? The AML batch endpoint default deployment, referencing one exact model version.
6. What is promotion evidence? Candidate metrics + policy + selected deployment/model recorded in gate/job/model artifacts.
7. Does Event Grid orchestrate the pipeline? No. AML pipeline state is authoritative; Event Grid handles asynchronous monitor/failure/retraining reactions.
8. How are duplicates prevented? Deterministic IDs, source cutoffs, Event Grid event IDs, exact model/deployment identities, and Snowflake `MERGE` keys.
9. How are delayed actuals handled? Pulled separately, canonicalized with the same mapping version, and used by asynchronous AML monitoring.
10. Is this production-ready? No; it is a capability-complete POC/template requiring tenant capability, security, cost, and live acceptance checks.

## Core PR vs Optional Follow-ups

Core: all R1-R16, local validation, public repository. Optional and excluded: Fabric ingestion, online endpoint, multi-environment promotion, private networking deployment, live cloud provisioning, automatic retraining enabled by default, enterprise incident integrations, cost benchmark.

## Evidence Links

- Azure ML Event Grid schema: https://learn.microsoft.com/en-us/azure/event-grid/event-schema-machine-learning
- Azure ML Event Grid integration: https://learn.microsoft.com/en-us/azure/machine-learning/how-to-use-event-grid?view=azureml-api-2
- Event Grid delivery/retry: https://learn.microsoft.com/en-us/azure/event-grid/delivery-and-retry
- Azure ML model monitoring: https://learn.microsoft.com/en-us/azure/machine-learning/how-to-monitor-model-performance?view=azureml-api-2
- Azure ML batch endpoints: https://learn.microsoft.com/en-us/azure/machine-learning/concept-endpoints-batch?view=azureml-api-2
- Azure ML managed Feature Store tutorial: https://learn.microsoft.com/en-us/azure/machine-learning/tutorial-get-started-with-feature-store?view=azureml-api-2
- Azure ML data-import migration: https://learn.microsoft.com/en-us/azure/machine-learning/data-import-migration-guide?view=azureml-api-2
- Snowflake Python connector pandas: https://docs.snowflake.com/en/developer-guide/python-connector/python-connector-pandas
- Snowflake Entra External OAuth: https://docs.snowflake.com/en/user-guide/oauth-azure

Architecture evidence retrieval gate: prior comparative research confirmed that a hybrid design requires explicit data snapshot, model, write-back, monitoring, identity, and ownership contracts and that Azure ML's Snowflake Data Import path is not a stable foundation.

## Recommendation

Implement the direct-pull AML-centered hybrid with explicit Snowflake boundaries, managed Feature Store adapter, MLflow/model assets, a batch endpoint production selector, asynchronous AML monitoring, and Event Grid as a retriable reaction/evidence bus rather than the critical workflow state machine.

## Next Steps

1. Build the batch-red tests and reconcile the expected failures.
2. Implement the smallest end-to-end fixture path, then add AML, Event Grid, monitoring, and IaC adapters.
3. Run all validation, clean-clone proof, secret audit, and final code-quality review.
4. Publish through a new public GitHub repository and verify `main` from the public URL.

## Ready for Execution

- [x] Objective, FR, NFR, and non-goals are explicit.
- [x] Intended operator and acceptance journey are explicit.
- [x] Affected systems and parts map to implementation, validation, and rollback.
- [x] Material edge cases and external failures have expected behavior.
- [x] Stateful/event logic has committed automated tests in Core scope.
- [x] Style references map to NFR8 and V1-V3.
- [x] Architecture evidence and current official sources are linked.
- [x] Exact validation and publication rollback are defined.
- [x] Most-likely-wrong cloud claim is explicit and is not used as completion evidence.
- [x] Closeout record includes delivered-vs-planned reconciliation, validation, review verdict, residual risks, and public delivery references.

## Closeout Record

**Status:** Delivered and published on 2026-07-14.

**Delivered versus planned:** R1-R16 are present: Snowflake pull/publish boundaries, exact-quantity contracts, AML components and lifecycle pipeline, MLflow/model promotion, managed Feature Store activation assets, batch deployment, model monitoring, Event Grid/Function reaction flow, managed identities/RBAC, Bicep, local fixtures, CI, operator runbooks, rollback procedures, and a source-indexed maturity roadmap. The direct-pull AML-centered architecture remains unchanged. The final hardening pass added cross-run promotion serialization, complete scoring identities, least-privilege Snowflake grants, credential-free monitor rendering, exact rollback commands, and stronger repository validation.

**Old-contract reconciliation:** Snowflake remains authoritative for source features, delayed actuals, and the single product-facing `PREDICTIONS` table. Exact-quantity mapping/version invariants remain explicit. AML remains authoritative for training, registry, deployment, orchestration, monitoring, and event reactions. Event Grid remains asynchronous evidence/reaction transport rather than workflow state.

**Validation evidence:**

- `python -m pytest -q`: 37 passed.
- Ruff lint and format checks, `compileall`, repository contract/public-safety validation, and `git diff --check`: passed.
- The pinned Azure ML SDK loaded all seven components, the lifecycle pipeline, runtime environment, Feature Store definitions, and rendered monitor schedule.
- Both Bicep templates compiled; the Python wheel and Azure Function ZIP packaged.
- All five local lifecycle scenarios passed twice with byte-identical artifacts.
- A clean clone installed `.[all]`, then passed tests, Ruff, SDK asset loading, repository validation, and the five-scenario demo.
- The staged secret-signature scan and repository forbidden-pattern scan returned no findings.
- GitHub Actions passed `bicep` in 28 seconds and `python-and-contracts` in 1 minute 28 seconds on PR #1.

**Review verdict:** `PASS_WITH_CAVEATS`. Two independent adversarial repair reviews rechecked runtime/data flow, security/RBAC, concurrency, monitoring, rollback, documentation, and evidence claims. Both reported no remaining P0-P2 findings after repairs. LSP was unavailable; symbol/reference coverage used repository search, imports/call sites, compiler/SDK loading, contract validation, and behavior tests.

**Residual risks:** Live Azure and Snowflake execution was intentionally not performed. Tenant capability/quota checks, Bicep `what-if`, managed-identity propagation, Snowflake External OAuth, Feature Store materialization, AML job submission, endpoint invocation, Event Grid delivery/dead-letter behavior, model-monitor execution, and transactional Snowflake publication remain unverified until a funded target subscription/account is supplied. The pinned SDK emits experimental/deprecation warnings while loading monitoring schemas. Level 3/4 maturity surfaces remain activation templates, not production-readiness claims.

**Public delivery:**

- Repository: https://github.com/Dodhon/azureml-snowflake-control-plane-poc
- Reviewed PR: https://github.com/Dodhon/azureml-snowflake-control-plane-poc/pull/1
- Merge commit: `4198edac485293b808e80123f5cf87d00cd54906`

**Rollback:** Revert merge commit `4198edac485293b808e80123f5cf87d00cd54906`, or make/delete the isolated public repository. No cloud or Snowflake resources were created or modified.
