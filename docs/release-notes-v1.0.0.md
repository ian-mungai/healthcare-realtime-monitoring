# v1.0.0 Release Notes

## Release scope

Version 1.0.0 is the first reproducible portfolio release of Healthcare Realtime Monitoring. The implementation baseline includes commit `5f7cc8b` with final evidence documentation added before tagging.

This release includes:

- A ten-patient synthetic realtime path from BIDMC-derived measurements through FHIR, Kinesis, Lambda, DynamoDB and IAM-authorized REST and WebSocket delivery.
- Separate live-cohort and model-readiness analytics dashboards with clinical-style ranges, freshness indicators, trend focus and explicit nonclinical labels.
- A governed analytical path through S3, Glue, Athena, dbt, Great Expectations, Soda and OpenLineage with an approval-gated synthetic-proxy scoring path.
- Terraform-managed networking, compute, storage, recovery, observability, GitHub OIDC and protected remote state.
- A canonical first-deployment quickstart plus guarded teardown, recreation and operations procedures.

## Release corrections

- Blood pressure now follows publication wall-clock time, so a five-second simulator cadence produces a BP observation every five minutes instead of every 25 minutes.
- GitHub deployment uses the existing service policies through a protected OIDC environment without long-lived AWS access keys.
- First-deployment instructions are consolidated in `docs/quickstart.md`; recovery and lifecycle documents link to that canonical path.
- Power BI connection and report-building guidance is complete while the private `.pbix` remains outside the repository.
- Every simulator task creates fresh encounters and randomly assigns normal or deterioration-proxy outcome scenarios without modifying the feature window.

## Acceptance evidence

Release checks completed on 2026-09-17:

- GitHub Actions passed Python checks, Terraform checks and all container builds for the release candidate.
- Local validation passed 466 Python tests with the required coverage, five workflow tests and Terraform validation.
- Terraform applied only the reviewed saved plan, reconciled computed values with a refresh-only plan and converged with no configuration changes.
- The post-deployment prerequisite audit passed, including state protection, encrypted configuration, GitHub OIDC and the confirmed alert subscription.
- All ten patient records were complete and current, all event timestamps advanced, all ten WebSocket connections were live and blood pressure republished after five minutes.
- All six realtime alarms were `OK` and both failure queues contained zero messages.
- The deployed simulator assigned random scenarios to all ten fresh encounters and completed a healthy ten-patient publication cycle.

## Boundaries

All data is synthetic or waveform-derived for engineering demonstration. The model target is a synthetic deterioration proxy, is not clinically validated and must not be used for patient care. Fresh-region model training and approval are intentionally deferred until repeated complete simulator runs produce both label classes in both patient-grouped partitions. MWAA remains manual-only while no model version is approved. Power BI Service publishing is optional and private. Deployment identifiers, credentials, Terraform state and the `.pbix` are not release artifacts.
