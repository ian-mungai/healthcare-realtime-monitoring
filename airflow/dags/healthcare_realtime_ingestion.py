"""Ingestion health, every 30 minutes: the FHIR webhook answers, HAPI's subscription to it is active and the webhook
Lambda had no errors. A failed check fails its task, so the workflow's task-failure alarm fires. The daily processing
pipeline is a separate workflow (healthcare_realtime_pipeline.py)."""

import os
from datetime import UTC, datetime, timedelta

from airflow.providers.standard.operators.python import PythonOperator
from lib.ingestion_health import check_recent_deliveries, check_subscription_active, check_webhook_health

from airflow import DAG

HAPI_FHIR_BASE_URL = os.environ["HAPI_FHIR_BASE_URL"]
API_STAGE_NAME = os.environ["API_STAGE_NAME"]
AWS_REGION = os.environ["AWS_REGION"]
# Every 30 minutes; the delivery check reads the same 30 minutes (lib/ingestion_health.py DELIVERY_WINDOW).
INGESTION_HEALTH_SCHEDULE = "*/30 * * * *"
DEFAULT_ARGS = {"owner": "healthcare_realtime", "depends_on_past": False, "retries": 1, "retry_delay": timedelta(minutes=1)}

with DAG(
    dag_id="healthcare_realtime_ingestion",
    description="Check FHIR webhook ingestion health",
    start_date=datetime(2026, 10, 8, tzinfo=UTC),
    schedule=INGESTION_HEALTH_SCHEDULE,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["healthcare", "fhir", "ingestion", "health"],
) as dag:
    check_webhook = PythonOperator(
        task_id="check_webhook_health", python_callable=check_webhook_health, op_kwargs={"stage": API_STAGE_NAME, "aws_region": AWS_REGION}
    )

    check_subscription = PythonOperator(
        task_id="check_subscription_active",
        python_callable=check_subscription_active,
        op_kwargs={"fhir_base_url": HAPI_FHIR_BASE_URL, "stage": API_STAGE_NAME, "aws_region": AWS_REGION},
    )

    check_deliveries = PythonOperator(task_id="check_recent_deliveries", python_callable=check_recent_deliveries, op_kwargs={"aws_region": AWS_REGION})

    check_webhook >> check_subscription >> check_deliveries
