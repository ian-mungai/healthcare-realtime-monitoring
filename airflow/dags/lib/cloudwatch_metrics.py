from __future__ import annotations

import os
from typing import Any

import boto3

AWS_REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
METRIC_NAMESPACE = "HealthcareRealtime/Pipeline"


def emit_metric(metric_name: str, value: float, *, unit: str = "Count", dimensions: list[dict[str, str]] | None = None) -> None:
    client = boto3.client("cloudwatch", region_name=AWS_REGION)

    metric: dict[str, Any] = {"MetricName": metric_name, "Value": value, "Unit": unit}

    if dimensions:
        metric["Dimensions"] = dimensions

    client.put_metric_data(Namespace=METRIC_NAMESPACE, MetricData=[metric])


def task_success_callback(context: dict[str, Any]) -> None:
    task_instance = context["task_instance"]

    emit_metric("TaskSuccess", 1, dimensions=[{"Name": "DagId", "Value": task_instance.dag_id}, {"Name": "TaskId", "Value": task_instance.task_id}])


def task_failure_callback(context: dict[str, Any]) -> None:
    task_instance = context["task_instance"]

    emit_metric("TaskFailure", 1, dimensions=[{"Name": "DagId", "Value": task_instance.dag_id}, {"Name": "TaskId", "Value": task_instance.task_id}])
