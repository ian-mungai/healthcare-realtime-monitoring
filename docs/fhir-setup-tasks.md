# FHIR Setup Tasks

The two deployment steps that write to HAPI FHIR, loading the ten-patient cohort and registering the Observation subscription, run as a one-off ECS task inside the project VPC. The task reaches the HAPI load balancer through the NAT gateway, which is the only address the load balancer accepts, so no operator machine needs network access to HAPI and no personal IP address is configured anywhere.

## How it runs

The `healthcare_realtime_fhir_setup` task definition is created in the foundation stage, alongside HAPI. It runs the vitals simulator image, which already contains the loader and the subscription code, in the private subnets of the HAPI cluster.

```zsh
./scripts/infrastructure/run_fhir_setup.sh load
./scripts/infrastructure/run_fhir_setup.sh register
```

1. `load` uploads the generated Synthea bundles from `scripts/synthea_loader/synthea/output/fhir/` to `seed/synthea/fhir/` in the data bucket, runs the task with the `load` command and waits for it to stop. The task selects the pinned ten-patient cohort, creates or reuses each Patient and Encounter in HAPI by Synthea identifier and writes the HAPI resource map to `FHIR_RESOURCE_MAP_S3_KEY`. The script then downloads the map to the local `FHIR_RESOURCE_MAP_FILE` path and renders the ten patient IDs into the ignored Terraform inputs.
2. `register` runs the task with the `register` command after the application stage has created the webhook. The task reads the webhook secret from Secrets Manager itself, looks for an existing Subscription with the same endpoint and criteria, and creates one only when none exists. The secret never leaves AWS.

Both commands are safe to repeat: the loader reuses existing resources and the registration reuses an existing subscription.

## E2E evidence

Every run, passed or failed, writes `report.json` and `report.md` to `artifacts/e2e/fhir_setup/<UTC time>_<command>/`. They record the code revision (and whether tracked files had uncommitted changes), the command, the task ARN, the container exit code, the stopped reason, the status and the run's limits. Task logs stay in CloudWatch under `/ecs/healthcare-realtime-fhir-setup`; the report never contains the webhook URL or secret.

## Behavior to verify

| Scenario | Input | Expected result |
| --- | --- | --- |
| First load | Ten or more generated bundles, empty HAPI | Ten Patients and Encounters created; map with ten cohort entries in S3 and locally; ten patient IDs rendered |
| Repeated load | Same bundles, HAPI already seeded | No duplicates; the same HAPI IDs in the map |
| First registration | Webhook deployed, no subscription | One active or requested Subscription pointing at the webhook |
| Repeated registration | Subscription already present | No new Subscription; the existing ID is reported |

## Failure scenarios

| Failure | Where it is caught | Result |
| --- | --- | --- |
| No generated bundles locally | `run_fhir_setup.sh load` before upload | Stops with a message to run `generate.sh`; no task starts |
| Fewer than ten usable bundles | Loader cohort selection in the task | Task exits non-zero; report status `failed` |
| HAPI not reachable (service starting, load balancer rule missing) | Loader or registration HTTP call | Task exits non-zero with a transport error; nothing written to the map |
| HAPI returns an error for a resource | Loader | Task exits non-zero; resources created before the error are reused on the next run |
| Map upload denied | Task role S3 permission | Task exits non-zero; the local map is not replaced |
| Webhook secret missing or malformed | Registration reads Secrets Manager | Task exits non-zero naming the secret ID, never its value |
| Webhook URL not HTTPS or not yet deployed | `run_fhir_setup.sh register` reads the Terraform output | Stops before starting the task |
| Task cannot start (image tag missing, no capacity) | `run_fhir_setup.sh` after `run-task` | Report status `failed` with the ECS failure reason |
| Task runs longer than the wait limit | `aws ecs wait tasks-stopped` | Script stops the task, report status `failed` |
| Another setup task already running | `run_fhir_setup.sh` before `run-task` | Stops without starting a second task |

## Limits

`tests/fhir_setup/` runs the task's `load` and `register` commands against a fake HAPI server and a fake S3 bucket, covering the first and repeated load, missing or too few bundles, a HAPI error, the first and repeated registration, a missing secret and a missing setting. It does not reach AWS: the ECS run, the NAT path to HAPI, the IAM permissions and the runner script are verified only by a run against a deployed stack and its report.
