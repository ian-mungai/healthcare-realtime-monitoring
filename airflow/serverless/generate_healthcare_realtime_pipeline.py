from __future__ import annotations

import importlib.util
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from airflow.providers.amazon.aws.operators.ecs import EcsRunTaskOperator
from airflow.providers.amazon.aws.operators.glue import GlueJobOperator
from airflow.providers.amazon.aws.sensors.glue import GlueJobSensor
from airflow.providers.amazon.aws.sensors.s3 import S3KeySensor
from airflow.providers.standard.operators.python import PythonOperator

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE = "healthcare_realtime_pipeline"
# Every DAG that becomes an MWAA Serverless workflow, by DAG file and workflow name.
WORKFLOWS = (PIPELINE, "healthcare_realtime_ingestion")


def dag_path(name: str) -> Path:
    return REPO_ROOT / "airflow" / "dags" / f"{name}.py"


def output_path(name: str) -> Path:
    return REPO_ROOT / "airflow" / "serverless" / "generated" / f"{name}.yaml"


DAG_PATH = dag_path(PIPELINE)
OUTPUT_PATH = output_path(PIPELINE)


def load_dag(name: str = PIPELINE):
    spec = importlib.util.spec_from_file_location(name, dag_path(name))

    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load DAG from {dag_path(name)}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module.dag


def serialize_dependencies(task) -> list[str]:
    return sorted(task.upstream_task_ids)


def normalize_task_definition(task_definition: str) -> str:
    family = task_definition.rsplit("/", maxsplit=1)[-1]
    name, separator, revision = family.rpartition(":")

    if separator and revision.isdigit():
        family = name

    if not family:
        raise ValueError("ECS task definition family must not be empty")

    return family


def serverless_start_date() -> datetime:
    value = os.environ.get("MWAA_SERVERLESS_START_DATE")

    if not value:
        raise ValueError("MWAA_SERVERLESS_START_DATE is required for MWAA Serverless generation")

    start_date = datetime.fromisoformat(value.replace("Z", "+00:00"))

    if start_date.tzinfo is None:
        raise ValueError("MWAA_SERVERLESS_START_DATE must include a timezone")

    if start_date <= datetime.now(UTC):
        raise ValueError("MWAA_SERVERLESS_START_DATE must be in the future")

    return start_date


def serialize_s3_sensor(task: S3KeySensor) -> dict[str, Any]:
    return {
        "operator": "airflow.providers.amazon.aws.sensors.s3.S3KeySensor",
        "bucket_name": task.bucket_name,
        "bucket_key": task.bucket_key,
        "wildcard_match": task.wildcard_match,
        "poke_interval": task.poke_interval,
        "timeout": task.timeout,
        "retries": task.retries,
        "retry_delay": int(task.retry_delay.total_seconds()),
        "dependencies": serialize_dependencies(task),
    }


def serialize_glue_operator(task: GlueJobOperator) -> dict[str, Any]:
    return {
        "operator": "airflow.providers.amazon.aws.operators.glue.GlueJobOperator",
        "job_name": task.job_name,
        "wait_for_completion": task.wait_for_completion,
        "retries": task.retries,
        "retry_delay": int(task.retry_delay.total_seconds()),
        "dependencies": serialize_dependencies(task),
    }


def serialize_glue_sensor(task: GlueJobSensor) -> dict[str, Any]:
    return {
        "operator": "airflow.providers.amazon.aws.sensors.glue.GlueJobSensor",
        "job_name": task.job_name,
        "run_id": task.run_id,
        "poke_interval": task.poke_interval,
        "timeout": task.timeout,
        "retries": task.retries,
        "retry_delay": int(task.retry_delay.total_seconds()),
        "dependencies": serialize_dependencies(task),
    }


def serialize_python_operator(task: PythonOperator) -> dict[str, Any]:
    callable_path = f"{task.python_callable.__module__}.{task.python_callable.__name__}"

    return {
        "operator": "airflow.providers.standard.operators.python.PythonOperator",
        "python_callable": callable_path,
        "op_kwargs": task.op_kwargs,
        "retries": task.retries,
        "retry_delay": int(task.retry_delay.total_seconds()),
        "dependencies": serialize_dependencies(task),
    }


def serialize_ecs_operator(task: EcsRunTaskOperator) -> dict[str, Any]:
    return {
        "operator": "airflow.providers.amazon.aws.operators.ecs.EcsRunTaskOperator",
        "cluster": task.cluster,
        "task_definition": normalize_task_definition(task.task_definition),
        "launch_type": task.launch_type,
        "overrides": task.overrides,
        "wait_for_completion": task.wait_for_completion,
        "network_configuration": task.network_configuration,
        "retries": task.retries,
        "retry_delay": int(task.retry_delay.total_seconds()),
        "dependencies": serialize_dependencies(task),
    }


def serialize_task(task) -> dict[str, Any]:
    if isinstance(task, S3KeySensor):
        return serialize_s3_sensor(task)

    if isinstance(task, GlueJobOperator):
        return serialize_glue_operator(task)

    if isinstance(task, GlueJobSensor):
        return serialize_glue_sensor(task)

    if isinstance(task, PythonOperator):
        return serialize_python_operator(task)

    if isinstance(task, EcsRunTaskOperator):
        return serialize_ecs_operator(task)

    raise TypeError(f"Unsupported task type for MWAA Serverless generation: {task.__class__.__module__}.{task.__class__.__name__}")


def validate_dag_contract(dag) -> None:
    if dag.catchup:
        raise ValueError("MWAA Serverless generation requires catchup=False")

    if dag.max_active_runs != 1:
        raise ValueError("MWAA Serverless generation requires max_active_runs=1")

    if dag.default_args.get("depends_on_past", False):
        raise ValueError("MWAA Serverless generation requires depends_on_past=False")

    if not dag.schedule:
        raise ValueError("MWAA Serverless generation requires a schedule")


def validate_task_contract(task) -> None:
    if task.depends_on_past:
        raise ValueError(f"MWAA Serverless generation does not support depends_on_past=True for task {task.task_id}")

    for callback_name in ("on_execute_callback", "on_retry_callback", "on_skipped_callback", "on_success_callback", "on_failure_callback"):
        if getattr(task, callback_name):
            raise ValueError(f"MWAA Serverless generation does not support {callback_name} for task {task.task_id}")


def build_workflow_definition(name: str = PIPELINE) -> dict[str, Any]:
    dag = load_dag(name)
    validate_dag_contract(dag)
    start_date = serverless_start_date()

    for task in dag.topological_sort():
        validate_task_contract(task)

    tasks = {task.task_id: serialize_task(task) for task in dag.topological_sort()}

    return {
        dag.dag_id: {
            "dag_id": dag.dag_id,
            "description": dag.description,
            "schedule": dag.schedule,
            "start_date": start_date.isoformat(),
            "max_active_runs": dag.max_active_runs,
            "tasks": tasks,
        }
    }


def main() -> None:
    for name in WORKFLOWS:
        path = output_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(build_workflow_definition(name), sort_keys=False), encoding="utf-8")
        sys.stdout.write(f"Generated {path}\n")


if __name__ == "__main__":
    main()
