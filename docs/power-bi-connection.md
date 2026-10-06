---
title: "Power BI Athena Connection"
description: "Connect a private desktop report to governed Athena tables."
last_updated: 2026-10-06
audience: [developer, operator]
---

# Power BI Athena Connection

For developers and operators: connect a private desktop report to governed Athena tables.

## Terminology

- **AWS**: Amazon Web Services.
- **BI**: business intelligence.
- **DSN**: data source name.
- **ODBC**: Open Database Connectivity.

## Example Placeholders

Angle-bracket values are placeholders. Replace each with the approved value for its named subject before running a command; keep real deployment values private.

- `<PROJECT_DATA_BUCKET>`: project data bucket for the selected environment or example.

## Before You Start

- Work from the repository root with the project virtual environment and the tools named in the [prerequisite inventory](external-prerequisites.md).
- Select the target environment with `PROJECT_ENV_FILE`; use the [environment safeguards](environments.md) before direct infrastructure or Amazon Web Services (AWS) commands.
- Obtain owner approval for deployment, publication, secret changes or destructive operations; examples do not grant authorization.
- Use Power BI Desktop on Windows and the Amazon Athena ODBC 2.x driver installed on that computer. AWS documents the [driver setup](https://docs.aws.amazon.com/athena/latest/ug/connect-with-odbc.html) and [Power BI connector](https://docs.aws.amazon.com/athena/latest/ug/connect-with-odbc-and-power-bi.html).
- Use an identity permitted to run Athena queries, read the required Glue tables and S3 objects, write the results prefix and call `athena:GetQueryResultsStream`.

## Scope

Status: connection acceptance recorded for v1.0.1.

This tutorial preserves the verified connection recorded in the [v1.0.1 release checklist](release-checklist.md#public-artifact-redaction). It does not certify a later deployment or native report rerun. Report construction is maintained locally and the `.pbix` is intentionally excluded from the repository.

## Configure the DSN

1. Open the 64-bit Windows ODBC Data Source Administrator.
2. Add an Amazon Athena ODBC 2.x data source.
3. Set a local data source name (DSN), the deployment region, `AwsDataCatalog` and the Athena workgroup used by the project.
4. Set the query-results location to `s3://<PROJECT_DATA_BUCKET>/athena_results/power_bi/`.
5. Select an authentication method available to the target AWS account using the permitted identity above.
6. Use the driver's **Test** action. Verify it succeeds before continuing.

Keep the DSN, credentials, account details and bucket value private. Do not commit an exported DSN or a `.pbix` file containing connection details.

## Connect Power BI Desktop

1. Open **Home > Get data**.
2. Search for **Amazon Athena** and select **Connect**.
3. Enter the DSN name.
4. Choose **Import** for this small portfolio dataset or **DirectQuery** for live Athena queries.
5. Choose **Use Data Source Configuration** when prompted for authentication.
6. Expand the catalog and analytical database in Navigator. Use `athena_catalog_name` and `dbt_database_name` in `config/deployment.defaults.json` (`awsdatacatalog` and `healthcare_realtime_dbt` unless overridden). Terraform passes these names to the dbt, Soda and scoring tasks; they are not set in the selected `${PROJECT_ENV_FILE:-.env}` file.
7. Confirm the tables named by `dbt_dim_patient_table_name`, `dbt_dim_encounter_table_name`, `dbt_dim_provider_table_name`, `dbt_encounter_features_table_name` and `dbt_ml_predictions_latest_table_name` in the same file are visible.

Successful table discovery completed the v1.0.1 Power BI connection requirement. The report file remains a private local artifact and is not required to reproduce the AWS data platform.
