import os
from datetime import UTC, datetime, timedelta

from airflow.providers.amazon.aws.operators.ecs import EcsRunTaskOperator
from airflow.providers.amazon.aws.operators.glue import GlueJobOperator
from airflow.providers.amazon.aws.sensors.glue import GlueJobSensor
from airflow.providers.amazon.aws.sensors.s3 import S3KeySensor
from airflow.providers.standard.operators.python import PythonOperator
from lib.athena_lineage import run_athena_validation

from airflow import DAG

RAW_BUCKET = os.environ["RAW_BUCKET"]
RAW_PREFIX = os.getenv("RAW_PREFIX", "raw/fhir_observations/")
GLUE_JOB_NAME = os.getenv("GLUE_JOB_NAME", "healthcare_realtime_raw_to_processed")
DATA_JOBS_ECS_CLUSTER = os.getenv("DATA_JOBS_ECS_CLUSTER", "healthcare-realtime-data-jobs")
DBT_ECS_TASK_DEFINITION = os.getenv("DBT_ECS_TASK_DEFINITION", "healthcare_realtime_dbt")
DBT_ECS_SECURITY_GROUP = os.getenv("AIRFLOW__DBT__ECS_SECURITY_GROUP", "")
DBT_ECS_SUBNETS = [subnet.strip() for subnet in os.getenv("AIRFLOW__DBT__ECS_SUBNETS", "").split(",") if subnet.strip()]
SODA_ECS_TASK_DEFINITION = os.getenv("SODA_ECS_TASK_DEFINITION", "healthcare_realtime_soda")
SODA_ECS_SECURITY_GROUP = os.getenv("AIRFLOW__SODA__ECS_SECURITY_GROUP", "")
SODA_ECS_SUBNETS = [subnet.strip() for subnet in os.getenv("AIRFLOW__SODA__ECS_SUBNETS", "").split(",") if subnet.strip()]
AIRFLOW_PIPELINE_SCHEDULE = os.getenv("AIRFLOW_PIPELINE_SCHEDULE", "0 2 * * *")
OPENLINEAGE_URL = os.getenv("OPENLINEAGE_URL", "")
DEFAULT_ARGS = {"owner": "healthcare_realtime", "depends_on_past": False, "retries": 2, "retry_delay": timedelta(minutes=1)}

with DAG(
    dag_id="healthcare_realtime_pipeline",
    description="Orchestrate incremental healthcare processing",
    start_date=datetime(2026, 8, 24, tzinfo=UTC),
    schedule=AIRFLOW_PIPELINE_SCHEDULE,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["healthcare", "fhir", "glue", "iceberg"],
) as dag:
    check_raw_data = S3KeySensor(
        task_id="check_raw_data", bucket_name=RAW_BUCKET, bucket_key=f"{RAW_PREFIX}*", wildcard_match=True, poke_interval=10, timeout=300
    )

    run_glue_job = GlueJobOperator(task_id="run_glue_job", job_name=GLUE_JOB_NAME, wait_for_completion=False)

    wait_for_glue_job = GlueJobSensor(
        task_id="wait_for_glue_job", job_name=GLUE_JOB_NAME, run_id="{{ ti.xcom_pull(task_ids='run_glue_job') }}", poke_interval=15, timeout=1800
    )

    validate_processed_data = PythonOperator(
        task_id="validate_processed_data", python_callable=run_athena_validation, op_kwargs={"data_bucket_name": RAW_BUCKET, "openlineage_url": OPENLINEAGE_URL}
    )

    run_great_expectations = EcsRunTaskOperator(
        task_id="run_great_expectations",
        cluster=DATA_JOBS_ECS_CLUSTER,
        task_definition=SODA_ECS_TASK_DEFINITION,
        launch_type="FARGATE",
        overrides={"containerOverrides": [{"name": "soda", "command": ["python", "/app/validate_processed_observations.py"]}]},
        wait_for_completion=True,
        network_configuration={"awsvpcConfiguration": {"subnets": SODA_ECS_SUBNETS, "securityGroups": [SODA_ECS_SECURITY_GROUP], "assignPublicIp": "DISABLED"}},
    )

    run_dbt_build = EcsRunTaskOperator(
        task_id="run_dbt_build",
        cluster=DATA_JOBS_ECS_CLUSTER,
        task_definition=DBT_ECS_TASK_DEFINITION,
        launch_type="FARGATE",
        overrides={},
        wait_for_completion=True,
        network_configuration={"awsvpcConfiguration": {"subnets": DBT_ECS_SUBNETS, "securityGroups": [DBT_ECS_SECURITY_GROUP], "assignPublicIp": "DISABLED"}},
    )

    run_soda_checks = EcsRunTaskOperator(
        task_id="run_soda_checks",
        cluster=DATA_JOBS_ECS_CLUSTER,
        task_definition=SODA_ECS_TASK_DEFINITION,
        launch_type="FARGATE",
        overrides={},
        wait_for_completion=True,
        network_configuration={"awsvpcConfiguration": {"subnets": SODA_ECS_SUBNETS, "securityGroups": [SODA_ECS_SECURITY_GROUP], "assignPublicIp": "DISABLED"}},
    )

    check_raw_data >> run_glue_job >> wait_for_glue_job >> validate_processed_data >> run_great_expectations >> run_dbt_build >> run_soda_checks
