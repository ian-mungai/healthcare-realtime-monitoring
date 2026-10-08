---
title: "v2.0.0 Release Notes"
description: "Read the scope, upgrade actions and recorded acceptance evidence for the v2.0.0 portfolio release."
last_updated: 2026-10-08
audience: [developer, operator]
---

# v2.0.0 Release Notes

For developers and operators: read the scope, upgrade actions and recorded acceptance evidence for the v2.0.0 portfolio release.

## Release Scope

Version 2.0.0 adds real-time early warning, Grafana dashboards, ingestion health checks and a local study environment. It also changes how a deployment keeps its Terraform state.

- **Real-time early warning:** `GET /patients/{patient_id}/early-warning` returns NEWS2 with its risk band and the approved model's score for the current encounter once its 15-minute feature window closes. The live dashboard shows both and a NEWS2 5+ count.
- **Grafana:** pipeline, quality and capacity dashboards run on the local warehouse and, with `ENABLE_GRAFANA=true`, on AWS through Athena behind an SSM port forward.
- **Ingestion health:** a 30-minute workflow checks the webhook, HAPI's subscription and webhook errors and raises the task-failure alarm on a failed check.
- **Local study environment:** a Docker stack with a 100-patient cohort, reproducible batch vitals, a local warehouse built by the same dbt models and a pre-specified simulation study. Warehouse rebuilds now repeat the study results exactly.
- **Simulation:** each deterioration encounter has its own outcome-window values. Normal encounters keep their variation inside the normal ranges.
- **Infrastructure:** Terraform state is local to the deploying checkout and teardown removes it. The HAPI and Marquez databases use `db.t3.micro`.

## Upgrade From v1

The deployment procedure changed in ways that break v1 operator steps:

1. There is no Terraform state bucket, bootstrap stack or remote backend. Run `./scripts/infrastructure/bootstrap.sh init` before the first plan; each `DEPLOYMENT_ENVIRONMENT` gets its own local workspace. Remove `TF_STATE_BUCKET` and `TF_STATE_PREFIX` from the environment file.
2. There is no GitHub deployment workflow or GitHub deployment role. Deploy from one local checkout with the [quickstart](quickstart.md). Remove the `GITHUB_*` and `ENABLE_GITHUB_OIDC` settings.
3. With Grafana enabled, create the `healthcare-realtime/grafana-admin` secret before the apply ([quickstart](quickstart.md#2-create-account-prerequisites) step 3).
4. Apply the current IAM policy templates with `infra/iam/scripts/manage_policies.py`; the S3 policy no longer covers a state bucket and the Secrets Manager policy only reads the Grafana secret.

## Acceptance Evidence

Release checks completed on Oct 8 2026 on the release code, in one deployment from empty local state:

- The IAM policy plan reported no changes across all 23 templates.
- FHIR setup `load`, `register` and `reference` passed.
- The application converged to `No changes`. After model activation, a refresh-only plan reconciled the computed workflow version and the plan again reported `No changes`.
- The end-to-end session passed the realtime, access, rejection and replay scenarios.
- The MWAA Serverless workflow ran Glue under its scoped role; the Iceberg optimizers were then enabled through a reviewed plan. With an approved model, one workflow run completed all ten tasks, including the cohort reference extract, dbt, scoring, the prediction refresh and Soda.
- The isolated load test passed with no missing observation in DynamoDB or over WebSocket: WebSocket delivery p50 241 ms, p95 1,381 ms.
- All 12 alarms were `OK`, both failure queues were empty and no replay policy remained.
- Teardown destroyed every resource and removed the local Terraform state and saved plans.
- Local validation passed 762 Python tests, Ruff, MyPy, the Soda contracts, the workflow tests, the Terraform plan tests and every repository hook.

## Boundaries

All data is synthetic or waveform-derived for engineering demonstration. The model target is a synthetic deterioration proxy and is not clinically validated; the model trained for this acceptance had four test encounters, which exercises the governed deployment path but supports no performance or clinical claim. Deployment identifiers, credentials and Terraform state are not release artifacts.
