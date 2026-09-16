# Power BI Athena Connection

## Scope

Status: completed.

This tutorial records the verified connection between Power BI Desktop and the project's Athena tables. Report construction is maintained locally and the `.pbix` is intentionally excluded from the repository.

Power BI Desktop runs on Windows. Install the current Amazon Athena ODBC 2.x driver on the same Windows computer. AWS documents both the [driver setup](https://docs.aws.amazon.com/athena/latest/ug/connect-with-odbc.html) and the [Power BI connector](https://docs.aws.amazon.com/athena/latest/ug/connect-with-odbc-and-power-bi.html).

## Configure the DSN

1. Open the 64-bit Windows ODBC Data Source Administrator and add an Amazon Athena ODBC 2.x data source.
2. Set a local DSN name, the deployment region, `AwsDataCatalog` and the Athena workgroup used by the project.
3. Set the query-results location to `s3://<project-data-bucket>/athena_results/power_bi/` and select an authentication method available to the target AWS account.
4. Ensure that identity can run Athena queries, read the required Glue tables and S3 objects, write the results prefix and call `athena:GetQueryResultsStream`.
5. Use the driver's **Test** action and stop until it succeeds.

Keep the DSN, credentials, account details and bucket value private. Do not commit an exported DSN or a `.pbix` file containing connection details.

## Connect Power BI Desktop

1. Open **Home > Get data**, search for **Amazon Athena** and select **Connect**.
2. Enter the DSN name and choose **Import** for this small portfolio dataset or **DirectQuery** for live Athena queries.
3. Choose **Use Data Source Configuration** when prompted for authentication.
4. In Navigator, expand the catalog and analytical database named by `ATHENA_CATALOG` and `ATHENA_DBT_DATABASE` in `.env`.
5. Confirm the tables named by `DBT_DIM_PATIENT_TABLE`, `DBT_DIM_ENCOUNTER_TABLE`, `DBT_DIM_PROVIDER_TABLE`, `DBT_ENCOUNTER_FEATURES_TABLE` and `DBT_ML_PREDICTIONS_LATEST_TABLE` are visible.

Successful table discovery completed the repository's Power BI connection requirement. The report file remains a private local artifact and is not required to reproduce the AWS data platform.
