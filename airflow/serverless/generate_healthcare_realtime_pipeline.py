from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import yaml
from airflow.providers.amazon.aws.operators.ecs import EcsRunTaskOperator
from airflow.providers.amazon.aws.operators.glue import GlueJobOperator
from airflow.providers.amazon.aws.sensors.glue import GlueJobSensor
from airflow.providers.amazon.aws.sensors.s3 import S3KeySensor
from airflow.providers.standard.operators.python import PythonOperator

REPO_ROOT = Path(__file__).resolve().parents[2]
DAG_PATH = REPO_ROOT / "airflow" / "dags" / "healthcare_realtime_pipeline.py"
OUTPUT_PATH = REPO_ROOT / "airflow" / "serverless" / "generated" / "healthcare_realtime_pipeline.yaml"


def load_dag():
    spec = importlib.util.spec_from_file_location("healthcare_realtime_pipeline", DAG_PATH)

    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load DAG from {DAG_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module.dag


def serialize_dependencies(task) -> list[str]:
    return sorted(task.upstream_task_ids)


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
        "retries": task.retries,
        "retry_delay": int(task.retry_delay.total_seconds()),
        "dependencies": serialize_dependencies(task),
    }


def serialize_ecs_operator(task: EcsRunTaskOperator) -> dict[str, Any]:
    return {
        "operator": "airflow.providers.amazon.aws.operators.ecs.EcsRunTaskOperator",
        "cluster": task.cluster,
        "task_definition": task.task_definition,
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


def build_workflow_definition() -> dict[str, Any]:
    dag = load_dag()
    tasks = {task.task_id: serialize_task(task) for task in dag.topological_sort()}

    return {dag.dag_id: {"dag_id": dag.dag_id, "tasks": tasks}}


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    definition = build_workflow_definition()
    OUTPUT_PATH.write_text(yaml.safe_dump(definition, sort_keys=False), encoding="utf-8")
    print(f"Generated {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
