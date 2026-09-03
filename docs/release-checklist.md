# Release Checklist

## Scope

Use this checklist to close a portfolio release of the healthcare realtime monitoring project. All published evidence must use synthetic data and replace deployment-specific values with placeholders.

Power BI report construction is tracked separately and is not a prerequisite for this repository release.

## Source and CI

- [ ] Working tree is clean.
- [ ] The intended commit is on `main` and pushed to the remote.
- [ ] GitHub Actions CI is green for that commit, including Python checks, Terraform checks, container builds, and Synthea validation when applicable.
- [ ] The release notes identify the commit without publishing account IDs, endpoint identifiers, bucket names, or secret material.

## Infrastructure convergence

- [ ] Run `terraform -chdir=infra fmt -check -recursive`.
- [ ] Run `terraform -chdir=infra validate`.
- [ ] Review `terraform -chdir=infra plan -var-file=development.tfvars`.
- [ ] Confirm each action is an intended deployment change. Do not apply a plan containing unexplained replacement, deletion, or permission broadening.
- [ ] Apply only an approved saved plan.
- [ ] Regenerate the MWAA Serverless workflow from the deployed Terraform outputs before applying workflow changes.
- [ ] Run Terraform plan again after deployment and confirm `No changes`.

The portability rollout intentionally changes the Glue job arguments, MWAA workflow definition, and dbt/Soda ECS task-definition revisions. These changes make the target bucket and region runtime configuration rather than repository constants.

## Realtime evidence

- [ ] Start exactly one simulator task using `scripts/demo/start_vitals_demo.sh`.
- [ ] Confirm the simulator is running with `scripts/demo/status_vitals_demo.sh`.
- [ ] Open the cohort dashboard and verify current measurements for every configured simulated patient.
- [ ] Confirm trend focus and cohort return behavior without losing other patient lines.
- [ ] Verify a REST latest-vitals response with AWS IAM authorization.
- [ ] Verify a WebSocket update with AWS IAM authorization.
- [ ] Confirm the event timestamp advances during the demonstration.
- [ ] Stop the simulator with `scripts/demo/stop_vitals_demo.sh` after evidence capture.

Detailed instructions are in [demo-guide.md](demo-guide.md).

## Data and operations evidence

- [ ] Confirm the end-to-end pipeline dashboard is healthy.
- [ ] Confirm the realtime dashboard shows current processing, low iterator age, and no sustained delivery errors.
- [ ] Confirm the live processing-latency and WebSocket-delivery alarms are `OK`.
- [ ] Record a successful MWAA workflow and its Glue, Athena, dbt, and Soda task outcomes.
- [ ] Record successful Great Expectations, Soda, and OpenLineage validation outcomes.
- [ ] Verify the failure queue and replay dead-letter queue are empty or contain only reviewed synthetic test records.

## Public-artifact redaction

Before committing screenshots, diagrams, examples, or portfolio documents:

- [ ] Remove account IDs, ARNs, ECR registry URLs, bucket names, API IDs, load-balancer names, endpoint URLs, connection IDs, private IPs, local usernames, and email addresses.
- [ ] Remove secrets, signed authorization headers, API keys, webhook values, Terraform state, and terminal output containing any of them.
- [ ] Replace environment values with reproducible placeholders such as `<aws-region>`, `<project-data-bucket>`, and `<api-id>`.
- [ ] Review every redaction-scan match manually; do not replace implementation configuration merely to conceal documentation.

## Release tag

Create a release tag only after CI is green, Terraform has converged, and the evidence checklist is complete:

```zsh
git tag -a v1.0.0 -m "Portfolio release v1.0.0"
git push origin v1.0.0
```
