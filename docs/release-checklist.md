# Release Checklist

## Scope

Use this checklist to close a portfolio release of the healthcare realtime monitoring project. All published evidence must use synthetic data and replace deployment-specific values with placeholders.

The portfolio release includes the completed Power BI-to-Athena connection and reporting documentation. The local `.pbix` remains outside the repository. Power BI Service publishing remains optional and private.

## Source and CI

- [x] Working tree is clean before tagging.
- [x] The release commit is on `main` and pushed to the remote.
- [x] GitHub Actions CI is green for the release commit, including Python checks, Terraform checks and container builds. Synthea validation may be skipped when its paths are unchanged.
- [x] The release notes identify the release scope without publishing account IDs, endpoint identifiers, bucket names or secret material.

## Infrastructure convergence

- [x] Run `./scripts/infrastructure/verify_reproducibility.sh` and confirm both builds produce identical artifact checksums and the empty-account tests pass.
- [x] Complete one deployment from an empty backend in a new region using `docs/quickstart.md`.
- [x] Run the guarded teardown and confirm only documented external prerequisites and the protected state bucket remain.
- [x] Run `./scripts/infrastructure/check_prerequisites.sh post-deploy` and confirm every automated prerequisite passes.
- [x] Run `terraform -chdir=infra fmt -check -recursive`.
- [x] Run `terraform -chdir=infra validate`.
- [x] Run `./scripts/infrastructure/render_project_config.sh --check`, then review `terraform -chdir=infra plan`.
- [x] Confirm each action is an intended deployment change with no unexplained replacement, deletion or permission broadening.
- [x] Apply only an approved saved plan.
- [x] Regenerate the MWAA Serverless workflow from deployed Terraform outputs before applying workflow changes.
- [x] Run Terraform plan again after deployment and confirm `No changes` after refresh-only reconciliation of computed values.
- [x] Confirm the main state backend is separate from application storage and the bootstrap state is backed up privately.

The portability rollout intentionally changes the Glue job arguments, MWAA workflow definition and dbt/Soda ECS task-definition revisions. These changes make the target bucket and region runtime configuration rather than repository constants.

## Realtime evidence

- [x] Start exactly one simulator task using `scripts/demo/start_vitals_demo.sh`.
- [x] Confirm the simulator is running with `scripts/demo/status_vitals_demo.sh`.
- [x] Open the cohort dashboard and verify current measurements for every configured simulated patient.
- [x] Open the separate model analytics dashboard and verify its readiness state, governance labels and separation from the live cohort dashboard.
- [x] Confirm trend focus and cohort return behavior without losing other patient lines.
- [x] Verify REST latest-vitals responses for all ten patients with AWS IAM authorization.
- [x] Verify live WebSocket delivery for all ten patients with AWS IAM authorization.
- [x] Confirm every patient event timestamp advances during the demonstration.
- [x] Stop the simulator with `scripts/demo/stop_vitals_demo.sh` after evidence capture.

Detailed instructions are in [demo-guide.md](demo-guide.md).

## Data and operations evidence

- [x] Confirm both Terraform-managed CloudWatch dashboards are present and their monitored services are healthy.
- [x] Confirm the realtime dashboard shows current processing, low iterator age and no sustained delivery errors.
- [x] Confirm all six realtime processing, iterator, delivery, error, throttle and replay alarms are `OK`.
- [x] Record successful Glue, Athena, Great Expectations, dbt, Soda and OpenLineage validation outcomes.
- [x] Confirm MWAA remains manual-only while `ML_APPROVED_MODEL_VERSION` is empty.
- [x] Verify the failure queue and replay dead-letter queue are empty.

Verified release evidence on 2026-09-16: the cohort dashboard displayed current measurements for all ten configured simulated patients; the model analytics dashboard displayed all ten Athena-backed approved-model scores with encounter, feature and governance context; one MWAA Serverless run completed all nine workflow tasks successfully; and the shared collector contained successful runs for all five expected analytical lineage jobs. Deployment-specific identifiers are intentionally omitted.

Verified release evidence on 2026-09-17: a fresh regional deployment completed from the quickstart; post-deployment prerequisites passed; GitHub OIDC was active; CI passed; Terraform converged; all ten live patients were current with active WebSocket connections; all realtime alarms were `OK`; and both failure queues were empty. The simulator published blood pressure on its documented five-minute wall-clock cadence. A later validation deployed random per-run scenarios, created fresh encounters for all ten patients and completed a healthy first cycle. Deployment-specific identifiers are intentionally omitted.

## Deferred model activation

These post-release operational steps are intentionally deferred and do not block the reproducible infrastructure, realtime or analytical platform release:

- [ ] Run enough complete 30-minute simulator sessions to produce both proxy-label classes in both patient-grouped partitions.
- [ ] Train, review and publish an immutable model artifact.
- [ ] Set `ML_APPROVED_MODEL_VERSION`, apply the reviewed Terraform plan and confirm MWAA changes from manual-only to the daily schedule.
- [ ] Run the full workflow and validate model scoring, prediction refresh and the populated model analytics dashboard in the fresh region.

## Public-artifact redaction

Before committing screenshots, diagrams, examples or portfolio documents:

- [x] Remove account IDs, ARNs, ECR registry URLs, bucket names, API IDs, load-balancer names, endpoint URLs, connection IDs, private IPs, local usernames and email addresses.
- [x] Remove secrets, signed authorization headers, API keys, webhook values, Terraform state and terminal output containing any of them.
- [x] Replace environment values with reproducible placeholders such as `<aws-region>`, `<project-data-bucket>` and `<api-id>`.
- [x] Review every redaction-scan match manually; do not replace implementation configuration merely to conceal documentation.
- [x] Confirm Power BI Desktop can connect to the Athena analytical tables through the Amazon Athena ODBC driver.
- [x] Complete the local Power BI report and keep the `.pbix` outside the repository.
- [x] Confirm the public release does not contain a `.pbix` binary or exported DSN.

## Release tag

Create a release tag only after CI is green, Terraform has converged and the evidence checklist is complete:

```zsh
git tag -a v1.0.0 -m "Portfolio release v1.0.0"
git push origin v1.0.0
```
