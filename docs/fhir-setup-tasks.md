---
title: "FHIR Setup Tasks"
description: "Load the synthetic cohort from inside the VPC and register the protected webhook."
last_updated: 2026-10-07
audience: [developer, operator]
---

# FHIR Setup Tasks

For developers and operators: load the synthetic cohort from inside the virtual private cloud (VPC) and register the protected webhook.

## Terminology

- **ARN**: Amazon Resource Name.
- **AWS**: Amazon Web Services.
- **E2E**: end-to-end.
- **ECS**: Elastic Container Service.
- **FHIR**: Fast Healthcare Interoperability Resources.
- **HTTP**: HyperText Transfer Protocol.
- **HTTPS**: HyperText Transfer Protocol Secure.
- **IAM**: Identity and Access Management.
- **ID**: identifier.
- **IP**: Internet Protocol.
- **NAT**: network address translation.
- **VPC**: virtual private cloud.
- **URL**: uniform resource locator.
- **UTC**: Coordinated Universal Time.

## Example Placeholders

Angle-bracket values are placeholders. Replace each with the approved value for its named subject before running a command; keep real deployment values private.

- `<COMMAND>`: command for the selected environment or example.

## Before You Start

- Work from the repository root with the project virtual environment and the tools named in the [prerequisite inventory](external-prerequisites.md).
- Select the target environment with `PROJECT_ENV_FILE`; use the [environment safeguards](environments.md) before direct infrastructure or Amazon Web Services (AWS) commands.
- Obtain owner approval for deployment, publication, secret changes or destructive operations; examples do not grant authorization.

## How It Runs

The two deployment steps that write to HAPI Fast Healthcare Interoperability Resources (FHIR), loading the ten-patient cohort and registering the Observation subscription, run as a one-off Elastic Container Service (ECS) task inside the project VPC. The task reaches the HAPI load balancer through the network address translation (NAT) gateway, which is the only address permitted by [the Terraform root](../infra/main.tf). Cohort setup requires no operator-machine access or personal Internet Protocol (IP) address. The [security reference](data-governance.md#security-and-access) describes this boundary.

The `healthcare_realtime_fhir_setup` task definition is created in the foundation stage, alongside HAPI. It runs the vitals simulator image, which already contains the loader and the subscription code, in the private subnets of the HAPI cluster.

1. Run the following command block:

   ```zsh
   ./scripts/infrastructure/run_fhir_setup.sh load
   ./scripts/infrastructure/run_fhir_setup.sh register
   ```

   To refresh the cohort reference tables outside the daily workflow, run `./scripts/infrastructure/run_fhir_setup.sh reference`.

   1. `load` uploads the generated Synthea bundles from `scripts/synthea_loader/synthea/output/fhir/` to `seed/synthea/fhir/` in the data bucket, runs the task with the `load` command and waits for it to stop. The task first waits up to 4 minutes for the HAPI capability statement, because a new HAPI target answers 502 or 503 until it passes the load balancer health check. It then selects the pinned ten-patient cohort, creates or reuses each Patient and Encounter in HAPI by Synthea identifier and writes the HAPI resource map to `FHIR_RESOURCE_MAP_S3_KEY`. The script then downloads the map to the local `FHIR_RESOURCE_MAP_FILE` path and renders the ten patient IDs into the ignored Terraform inputs.
   2. `register` runs the task with the `register` command after the application stage has created the webhook. The task reads the webhook secret from Secrets Manager itself, looks for an existing Subscription with the same endpoint and criteria and creates one only when none exists. The secret never leaves AWS.

   3. `reference` writes the cohort reference tables. The daily workflow runs it before dbt (task `extract_cohort_reference`), so the admissions include every simulator run. The task downloads the resource map and the Synthea bundles, waits for HAPI and reads the simulator's encounters. It writes five tables as JSON lines to `reference/cohort/<table>/<table>.json` in the data bucket: demographics, payer history, facilities, admissions and waveform split groups. Each table is one object at a fixed key, replaced whole. Glue tables of the same names in the source database read them. dbt builds the reference models from them ([Analytics Star Schema](analytics-star-schema.md#cohort-reference-models)). Encounters of patients outside the cohort and of the batch null control are skipped and counted. The prefix is outside `raw/`, which the Glue job reads recursively.

   All three commands are safe to repeat. The loader reuses existing resources, the registration reuses an existing subscription and the reference extract replaces its objects.

## E2E Evidence

Every run, passed or failed, writes `report.json` and `report.md` to `artifacts/e2e/fhir_setup/<UTC_TIME>_<COMMAND>/`. They record the code revision (and whether tracked files had uncommitted changes), the command, the task identifier (ID) (never the full Amazon Resource Name (ARN), which contains the account ID), the container exit code, the stopped reason, the status and the run's limits. Task logs stay in CloudWatch under `/ecs/healthcare-realtime-fhir-setup`; the report never contains the webhook URL or secret.

## Behavior to Verify

| Scenario | Input | Expected result |
| --- | --- | --- |
| First load | Ten or more generated bundles, empty HAPI | Ten Patients and Encounters created; map with ten cohort entries in S3 and locally; ten patient IDs rendered |
| Repeated load | Same bundles, HAPI already seeded | No duplicates; the same HAPI IDs in the map |
| First registration | Webhook deployed, no subscription | One active or requested Subscription pointing at the webhook |
| Repeated registration | Subscription already present | No new Subscription; the existing ID is reported |
| Reference extract | Map and bundles in S3, simulator encounters in HAPI | One JSON-lines object per reference table under `reference/cohort/`; a rerun writes identical objects |

## Failure Scenarios

| Failure | Where it is caught | Result |
| --- | --- | --- |
| No generated bundles locally | `run_fhir_setup.sh load` before upload | Stops with a message to run `generate.sh`; no task starts |
| Fewer than ten usable bundles | Loader cohort selection in the task | Task exits non-zero; report status `failed` |
| HAPI still starting (target not yet healthy) | `load` readiness wait on `/metadata` | Retries HyperText Transfer Protocol (HTTP) 502, 503, 504 and connection errors every 10 seconds; exits non-zero after 4 minutes; nothing written to HAPI or the map |
| HAPI not reachable (service starting, load balancer rule missing) | Loader or registration HTTP call | Task exits non-zero with a transport error; nothing written to the map |
| HAPI returns an error for a resource | Loader | Task exits non-zero; resources created before the error are reused on the next run |
| Map upload denied | Task role S3 permission | Task exits non-zero; the local map is not replaced |
| Reference extract before the cohort is loaded | `reference` downloads the resource map | Task exits non-zero before writing anything |
| Webhook secret missing or malformed | Registration reads Secrets Manager | Task exits non-zero naming the secret ID, never its value |
| Webhook URL not HyperText Transfer Protocol Secure (HTTPS) or not yet deployed | `run_fhir_setup.sh register` reads the Terraform output | Stops before starting the task |
| Task cannot start (image tag missing, no capacity) | `run_fhir_setup.sh` after `run-task` | Report status `failed` with the ECS failure reason |
| Task runs longer than the wait limit | `aws ecs wait tasks-stopped` | Script stops the task, report status `failed` |
| Another setup task already running | `run_fhir_setup.sh` before `run-task` | Stops without starting a second task |

## Limits

`tests/fhir_setup/` runs the task's `load`, `register` and `reference` commands against a fake HAPI server and a fake S3 bucket, covering the first and repeated load, missing or too few bundles, a HAPI that becomes ready late or never, a HAPI error, the first and repeated registration, a missing secret and a missing setting. It does not reach AWS: the ECS run, the NAT path to HAPI, the Identity and Access Management (IAM) permissions and the runner script are verified only by a run against a deployed stack and its report.

## Artifact Path Placeholders

- `<UTC_TIME>`: UTC timestamp generated by the runner.
- `<RUN_ID>`: unique run identifier generated by the runner.

These path components are output labels; you do not enter them as deployment inputs.
