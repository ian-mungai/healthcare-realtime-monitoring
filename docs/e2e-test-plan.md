# End-to-End Test Plan

**Status: Confirmed** by the repository owner on Sep 29 2026. The first iteration is in progress; the other scenarios are planned.

## Goal

Prove the platform's behavior through its real entry points and record a repeatable report for every run, instead of relying on unit tests and the manual [release checklist](release-checklist.md). Each scenario starts where a user or upstream system starts (a simulator task, a webhook call, a signed API request, a workflow run) and checks the observable result (DynamoDB state, an API response, a WebSocket message, an Athena table, a queue, an alarm).

## Principles

1. **Real path, deployed stack.** Scenarios run against a deployed development stack. Mocks and fakes stay in the unit suite; an E2E scenario never replaces the component it checks.
2. **One report per run.** Every run, passed, failed or blocked, writes `report.json` and `report.md` to `artifacts/e2e/<scenario>/<UTC time>_<run id>/`, following the existing load-test and FHIR-setup reports: code revision and uncommitted changes, inputs and seeds, expected and observed results per check, status, evidence (counts, IDs, timings) and limits. Reports never contain account IDs, endpoints, secrets or signed headers.
3. **Failure cases first.** Each scenario lists its failure modes before its code is written, and each negative check must fail for its intended reason.
4. **Safe to repeat.** Scenarios clean up what they create or use isolated resources, and a second run on the same input gives the same result.
5. **Existing tests stay** until a scenario covers their behavior. Removing a test later needs, per test: its name and location, the failure it detects, the stronger coverage that replaces it, why it existed and what removing it unlocks.
6. **Cost control.** Scenarios run in one deployment session that ends with the guarded teardown. At the project's roughly $10 per day while deployed, a three-hour session costs on the order of a few dollars.

## Runner

The `e2e/` package has one entry point, `python -m e2e.run <scenario> [--env-file PATH]`, and a session wrapper, `python -m e2e.run session`, that runs the implemented scenarios in order. Shared pieces: loading `.env` and Terraform outputs, SigV4-signed REST and WebSocket clients (reusing the dashboard's signing code), polling with deadlines, and the report writer. The existing `run_fhir_setup.sh` and `scripts/load_testing/realtime_load_test.py` stay as they are.

```zsh
.venv/bin/python -m e2e.run realtime     # or access, rejection, replay
.venv/bin/python -m e2e.run session      # every implemented scenario in order
```

Run them only against a deployed development stack, with exactly the ten-patient cohort loaded and no simulator task running, then tear the stack down.

## Scenarios

| ID | Path | Entry point | Pass condition | Failure modes checked | Today |
| --- | --- | --- | --- | --- | --- |
| E1 | FHIR setup | `run_fhir_setup.sh load` and `register` | Ten patients and encounters in HAPI; one subscription; map rendered | Missing bundles, HAPI unreachable, secret missing, repeated run | Exists, report per run |
| E2 | Realtime ingest | One simulator task, 3 cycles | Latest vitals for all ten patients in DynamoDB within 60 s of each cycle; timestamps advance | Simulator failure ratio, webhook 5xx, processor errors | Manual checklist |
| E3 | REST read | SigV4 `GET /patients/{id}/vitals` for each patient | 200 with fresh values for all ten | Stale data, 403 for an allowed principal | Manual (Postman) |
| E4 | WebSocket delivery | SigV4 WebSocket connection during E2 | A message for every patient within one cycle | Connection refused, missing patients, stale connections left behind | Manual (Postman) |
| E5 | Access control | Unsigned REST call, wrong webhook secret, principal outside the access policy | 403 or 401 each time; no patient data returned | A check that passes for the wrong reason, e.g. a 5xx | Unit tests only |
| E6 | Load and latency | `realtime_load_test.py` on the isolated stream | Latency percentiles within the documented limits | Throttling, dropped events | Exists, report per run |
| E7 | Failure and replay | A deliberately malformed record on the test stream | Record reaches the failure queue, replay republishes once, the poison record ends in the dead-letter queue; queues drained at the end | Infinite replay, silent drop | Unit tests only |
| E8 | Analytical batch | MWAA workflow run (Glue, Great Expectations, dbt, Soda, OpenLineage) | Every step succeeds; row counts reconcile from raw to processed to staging to marts; dbt build tests pass; lineage events present | Quality gate failure stops the workflow; a second run yields identical results | Manual checklist |
| E9 | Quarantine | An invalid observation in the raw landing | One quarantine row with the expected rejection reason; valid rows unaffected | Invalid row leaking into processed data | Unit tests only |
| E10 | Model scoring | Approved-model scoring task | Predictions in the serving and latest tables with governance labels; the model dashboard query returns them | Missing approved version keeps MWAA manual-only | Manual checklist |
| E11 | Operations signals | CloudWatch alarms and queues after the session | All realtime alarms `OK`; failure and dead-letter queues empty | Alarm left in `ALARM` | Manual checklist |
| E12 | Lifecycle | Bootstrap from an empty backend, convergence plan, guarded teardown | Convergence plan reports no changes; teardown leaves only the documented prerequisites | Drift after apply, orphaned resources | Manual checklist and `verify_reproducibility.sh` |

## Existing unit tests

About 480 pytest tests and 5 workflow tests cover pure logic: FHIR mapping and sanitizing, schema validation, SQL and policy rendering, dashboards' data shaping and the check tooling. They stay. After a scenario has passed in a real run, the unit tests it duplicates at a weaker boundary become candidates for removal, each with the evidence in principle 5. Tests of pure logic that no scenario exercises directly, such as the vital-sign catalog contract and the IAM policy renderer, stay permanently.

## Decisions

1. **First iteration** (Sep 29 2026): the runner and report writer, then the realtime path (E2 to E5 and E7). E8 and E9 follow, then E10 to E12.
2. **No local tier** (Sep 29 2026): no AWS emulator. Local checks remain the unit suite and CI.
3. **Deployment sessions** need the owner's approval each time.

## First iteration

`python -m e2e.run realtime`, `access`, `rejection` and `replay` implement E2 to E5 and E7. Each reads `.env`, the Terraform outputs and the ten cohort patient IDs from the local resource map, and writes its report even when it stops early; a missing prerequisite gives status `blocked`.

### realtime (E2, E3, E4)

1. Before: every patient's latest reading through the signed REST API (the baseline) and a signed WebSocket subscription per patient.
2. Run one vitals simulator task with `SIMULATOR_MAX_CYCLES=3` and wait up to 5 minutes for it to stop.
3. Checks: the task exits 0; each of the ten patients has a REST reading newer than its baseline; each patient's WebSocket received at least one message for that patient; the REST response carries every vital field the simulator sends.
4. Failure modes: the task cannot start or exits non-zero (logs named in the report); a patient never updates (the patient is named, never its values); a WebSocket connection is refused or silent; the run exceeds its deadline. Connections are always closed and a still-running task is stopped.

### access (E5)

1. An unsigned REST request for a cohort patient must be refused with 403.
2. A signed REST request for a patient outside the cohort must be refused with 403 and the message "Access to this patient is not authorized", so a gateway error cannot pass for an authorization decision.
3. The webhook health route with a wrong secret must return 401 with "Invalid webhook secret".
4. An unsigned WebSocket connection must be refused during the handshake.
5. A principal outside the access policy needs a second AWS identity; the check is reported as not run until one is configured.

### rejection (part of E7)

1. The failure queue and the replay dead-letter queue are empty before the run.
2. One record with an unsupported `schema_version` goes onto the isolated load-test stream.
3. Checks: within 5 minutes the processor's `PermanentRecordsRejected` metric counts it, and both queues are still empty, because a permanent error is rejected rather than retried or replayed.

### replay (rest of E7)

Owner's decision, Sep 29 2026: cause a real, temporary write failure instead of adding a failure switch to production code.

1. The failure queue and the replay dead-letter queue are empty before the run.
2. An explicit Deny on the processor role blocks DynamoDB writes to the latest-vitals table for one synthetic patient only (a `dynamodb:LeadingKeys` condition), and the run waits 45 seconds for IAM to apply it. The ten cohort patients are unaffected.
3. One valid record for that patient goes onto the main stream, because the replay Lambda only replays the main stream.
4. Checks: within 10 minutes the record reaches the replay dead-letter queue carrying `_replay_attempt` 1 and a "replay limit reached" reason, which proves the failure queue, one replay and the terminal path; no latest-vitals item exists for the synthetic patient; both queues are empty afterwards.
5. Always, even after a failure: the Deny is removed, any item for the synthetic patient is deleted and the run's dead-letter message is removed.
6. Side effect: the synthetic record and its one replay also reach raw storage through Firehose. The analytical models exclude patients outside the cohort, and the report says so.

## Deployment session runbook

One session deploys the development stack, runs the scenarios and tears everything down. Budget about three hours; at roughly $10 per day while deployed, that is a few dollars. Each apply and the teardown need the owner's go-ahead.

1. **Before, no cost:** local CI passes on `main`; `.env` is complete; the AWS login for the development account works (`./scripts/infrastructure/check_prerequisites.sh local`).
2. **IAM templates:** plan, review and apply them with `infra/iam/scripts/manage_policies.py` ([external prerequisites](external-prerequisites.md)). They changed since the last deployment.
3. **Deploy:** follow the [quickstart](quickstart.md) steps 3 and 4: repositories, images, foundation, `run_fhir_setup.sh load`, application, convergence plan (`No changes`) and `run_fhir_setup.sh register`.
4. **Test:** `.venv/bin/python -m e2e.run session`, then the [load test](load-testing.md). Also run the Glue job once, since its permissions changed, and confirm the realtime alarms are `OK`.
5. **Evidence:** review the reports under `artifacts/e2e/`; commit the ones kept as evidence.
6. **Teardown:** `teardown.sh prepare-plan` and `destroy-plan` with `CONFIRM_TEARDOWN`, then the storage cleanup and verification in the [infrastructure lifecycle guide](infrastructure-lifecycle.md).

