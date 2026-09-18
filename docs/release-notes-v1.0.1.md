# v1.0.1 Release Notes

## Release scope

Version 1.0.1 completes the approval-gated synthetic model path introduced in v1.0.0. It preserves the reproducible realtime, analytical and infrastructure baseline while adding a reviewed immutable model artifact, daily scoring and validated model analytics.

## Model activation

- Repeated complete simulator sessions produced both synthetic proxy-label classes in the patient-grouped training and test partitions.
- The reviewed logistic-regression baseline was published as an immutable checksummed artifact in encrypted project storage.
- Terraform granted model-specific least-privilege access, deployed the approved version to the dbt task definition and changed MWAA Serverless from manual-only operation to the daily schedule.
- ML scoring, prediction-model refresh and Soda validation passed independently before the final end-to-end run.
- The model analytics dashboard now reads the approved-model view with one current score for each of the ten configured patients.

## Acceptance evidence

Release checks completed on 2026-09-18:

- The training partition contained 18 eligible encounters across both labels and the test partition contained two eligible encounters across both labels.
- One final MWAA Serverless run completed all nine workflow tasks successfully in under 25 minutes.
- Fresh OpenLineage events were present for Glue, Athena, Great Expectations, dbt and Soda.
- Local validation passed 466 Python tests at 68.63% coverage, five Airflow workflow tests and five Terraform empty-account plan tests.
- GitHub Actions passed Python checks, Terraform checks and all container builds for the release commit.
- Terraform reconciled computed workflow metadata through a reviewed refresh-only plan then reported `No changes`.

## Boundaries

All data is synthetic or waveform-derived for engineering demonstration. The model target is a synthetic deterioration proxy and is not clinically validated. The two-row test partition is sufficient to exercise the governed deployment path but not to support performance or clinical claims. Power BI Service publishing remains optional and private. Deployment identifiers, credentials, Terraform state and the `.pbix` are not release artifacts.
