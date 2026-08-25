import json
import os
import time
from datetime import UTC, datetime, timedelta

import boto3
from airflow.exceptions import AirflowException
from airflow.sdk import dag, task

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
GLUE_JOB_NAME = os.getenv("GLUE_JOB_NAME", "healthcare_realtime_raw_to_processed")
RAW_BUCKET = os.getenv("RAW_BUCKET", "imungai-healthcare-realtime")
RAW_PREFIX = os.getenv("RAW_PREFIX", "raw/fhir_observations/")
METRICS_PREFIX = os.getenv("METRICS_PREFIX", "metrics/glue/")
GLUE_DATABASE = os.getenv("GLUE_DATABASE", "healthcare_realtime")
GLUE_TABLE = os.getenv("GLUE_TABLE", "processed_fhir_observations")
ATHENA_OUTPUT = f"s3://{RAW_BUCKET}/athena_results/"


def build_client(service_name: str):
    return boto3.client(service_name, region_name=AWS_REGION)


def wait_for_glue_job(glue_client, job_run_id: str) -> None:
    terminal_states = {"SUCCEEDED", "FAILED", "STOPPED", "TIMEOUT", "ERROR"}

    while True:
        response = glue_client.get_job_run(JobName=GLUE_JOB_NAME, RunId=job_run_id, PredecessorsIncluded=False)

        state = response["JobRun"]["JobRunState"]

        if state in terminal_states:
            break

        time.sleep(30)

    if state != "SUCCEEDED":
        raise AirflowException(f"Glue job {job_run_id} finished with state {state}")


def wait_for_athena_query(athena_client, query_execution_id: str) -> None:
    terminal_states = {"SUCCEEDED", "FAILED", "CANCELLED"}

    while True:
        response = athena_client.get_query_execution(QueryExecutionId=query_execution_id)

        state = response["QueryExecution"]["Status"]["State"]

        if state in terminal_states:
            break

        time.sleep(5)

    if state != "SUCCEEDED":
        reason = response["QueryExecution"]["Status"].get("StateChangeReason", "Unknown Athena failure")

        raise AirflowException(f"Athena query failed: {reason}")


def read_latest_metric(s3_client) -> dict:
    response = s3_client.list_objects_v2(Bucket=RAW_BUCKET, Prefix=METRICS_PREFIX)

    objects = response.get("Contents", [])

    if not objects:
        raise AirflowException("No Glue metrics objects found")

    latest_object = max(objects, key=lambda item: item["LastModified"])

    metric_object = s3_client.get_object(Bucket=RAW_BUCKET, Key=latest_object["Key"])

    metric_body = metric_object["Body"].read().decode("utf-8").strip()

    if not metric_body:
        raise AirflowException("Latest Glue metrics object is empty")

    return json.loads(metric_body.splitlines()[-1])


@dag(
    dag_id="healthcare_realtime_pipeline",
    description="Orchestrate incremental healthcare processing with MWAA",
    start_date=datetime(2026, 8, 24, tzinfo=UTC),
    schedule="*/15 * * * *",
    catchup=False,
    max_active_runs=1,
    default_args={"owner": "healthcare_realtime", "depends_on_past": False, "retries": 2, "retry_delay": timedelta(minutes=1)},
    tags=["healthcare", "fhir", "glue", "iceberg"],
)
def healthcare_realtime_pipeline():
    @task
    def check_raw_data() -> int:
        s3_client = build_client("s3")

        response = s3_client.list_objects_v2(Bucket=RAW_BUCKET, Prefix=RAW_PREFIX, MaxKeys=1)

        if response.get("KeyCount", 0) == 0:
            raise AirflowException(f"No raw FHIR data found at s3://{RAW_BUCKET}/{RAW_PREFIX}")

        return response["KeyCount"]

    @task
    def run_glue_job() -> str:
        glue_client = build_client("glue")

        response = glue_client.get_job_runs(JobName=GLUE_JOB_NAME, MaxResults=10)

        active_runs = [run for run in response.get("JobRuns", []) if run["JobRunState"] in {"STARTING", "RUNNING", "STOPPING", "WAITING"}]

        if active_runs:
            job_run_id = active_runs[0]["Id"]

            print(f"Existing Glue job is active: {job_run_id}")

            print("Waiting for the existing Glue run instead of starting another run.")

            wait_for_glue_job(glue_client, job_run_id)

            return job_run_id

        response = glue_client.start_job_run(JobName=GLUE_JOB_NAME)

        job_run_id = response["JobRunId"]

        print(f"Started Glue job: {job_run_id}")

        wait_for_glue_job(glue_client, job_run_id)

        return job_run_id

    @task
    def check_glue_metrics(job_run_id: str) -> dict:
        s3_client = build_client("s3")
        metric = read_latest_metric(s3_client)

        print(f"Glue job run: {job_run_id}")

        print(f"Candidate count: {metric['candidate_count']}")

        print(f"Valid count: {metric['valid_count']}")

        print(f"Rejected count: {metric['rejected_count']}")

        return metric

    @task
    def validate_processed_data(metric: dict) -> None:
        athena_client = build_client("athena")

        query = f"""
        SELECT COUNT(*) AS invalid_count
        FROM {GLUE_DATABASE}.{GLUE_TABLE}
        WHERE observation_id IS NULL
           OR patient_id IS NULL
           OR patient_id = ''
           OR loinc_code IS NULL
           OR value IS NULL
           OR effective_datetime IS NULL
        """

        response = athena_client.start_query_execution(QueryString=query, QueryExecutionContext={"Database": GLUE_DATABASE}, ResultConfiguration={"OutputLocation": ATHENA_OUTPUT})

        query_execution_id = response["QueryExecutionId"]

        wait_for_athena_query(athena_client, query_execution_id)

        results = athena_client.get_query_results(QueryExecutionId=query_execution_id)

        rows = results["ResultSet"]["Rows"]

        if len(rows) < 2:
            raise AirflowException("Athena validation returned no data row")

        invalid_count = int(rows[1]["Data"][0]["VarCharValue"])

        print(f"Glue candidates: {metric['candidate_count']}")

        print(f"Processed table invalid rows: {invalid_count}")

        if invalid_count > 0:
            raise AirflowException(f"Processed Iceberg table contains {invalid_count} invalid rows")

    raw_data = check_raw_data()
    glue_run = run_glue_job()
    metrics = check_glue_metrics(glue_run)
    validation = validate_processed_data(metrics)

    raw_data >> glue_run
    glue_run >> metrics
    metrics >> validation


healthcare_realtime_pipeline()
