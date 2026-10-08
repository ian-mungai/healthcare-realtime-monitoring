from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import generate_healthcare_realtime_pipeline as generator
import validate_generated_workflow as validator
import yaml


class WorkflowGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = patch.dict(
            os.environ,
            {
                "RAW_BUCKET": "ci-project-data-bucket",
                "RAW_PREFIX": "raw/example/",
                "GLUE_JOB_NAME": "example-glue-job",
                "AIRFLOW_PIPELINE_SCHEDULE": "0 2 * * *",
                "AWS_REGION": "example-region-1",
                "PROJECT_NAME": "example-project",
                "ATHENA_SOURCE_DATABASE": "example_source",
                "ATHENA_PROCESSED_TABLE": "example_processed",
                "ATHENA_WORKGROUP": "example-workgroup",
                "ATHENA_RESULTS_S3_URI": "s3://ci-project-data-bucket/athena-results/",
                "AIRFLOW__DBT__ECS_SECURITY_GROUP": "sg-ci-placeholder",
                "AIRFLOW__DBT__ECS_SUBNETS": "subnet-ci-a,subnet-ci-b",
                "AIRFLOW__SODA__ECS_SECURITY_GROUP": "sg-ci-placeholder",
                "AIRFLOW__SODA__ECS_SUBNETS": "subnet-ci-a,subnet-ci-b",
                "DBT_ECS_TASK_DEFINITION": ("arn:aws:ecs:example-region-1:111111111111:task-definition/healthcare_realtime_dbt:42"),
                "SODA_ECS_TASK_DEFINITION": "healthcare_realtime_soda:17",
                "FHIR_SETUP_ECS_TASK_DEFINITION": "healthcare_realtime_fhir_setup:3",
                "AIRFLOW__FHIR_SETUP__ECS_SECURITY_GROUP": "sg-ci-placeholder",
                "AIRFLOW__FHIR_SETUP__ECS_SUBNETS": "subnet-ci-a,subnet-ci-b",
                "DATA_JOBS_ECS_CLUSTER": "healthcare-realtime-data-jobs",
                "MWAA_SERVERLESS_START_DATE": "2099-01-01T00:00:00+00:00",
                "OPENLINEAGE_URL": "https://lineage.example.com",
                "HAPI_FHIR_BASE_URL": "http://hapi.example.com/fhir",
                "API_STAGE_NAME": "development",
            },
            clear=False,
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_native_dag_has_daily_schedule_and_expected_chain(self) -> None:
        dag = generator.load_dag()

        self.assertEqual(dag.schedule, "0 2 * * *")
        self.assertFalse(dag.catchup)
        self.assertEqual(dag.max_active_runs, 1)
        self.assertEqual(len(dag.tasks), 10)
        self.assertEqual(dag.task_dict["run_great_expectations"].upstream_task_ids, {"validate_processed_data"})
        self.assertEqual(dag.task_dict["extract_cohort_reference"].upstream_task_ids, {"run_great_expectations"})
        self.assertEqual(dag.task_dict["run_dbt_build"].upstream_task_ids, {"extract_cohort_reference"})
        self.assertEqual(dag.task_dict["run_ml_scoring"].upstream_task_ids, {"run_dbt_build"})
        self.assertEqual(dag.task_dict["refresh_prediction_models"].upstream_task_ids, {"run_ml_scoring"})
        self.assertEqual(dag.task_dict["run_soda_checks"].upstream_task_ids, {"refresh_prediction_models"})

    # The ingestion workflow's health checks. Failure modes: the checks run in parallel, so a dead webhook also
    # reports a misleading subscription result; the schedule differs from the 30-minute window the delivery check
    # reads; a check's settings are missing from the generated file, so it runs against nothing.
    def test_ingestion_dag_chains_the_three_checks_every_30_minutes(self) -> None:
        dag = generator.load_dag("healthcare_realtime_ingestion")

        self.assertEqual(dag.schedule, "*/30 * * * *")
        self.assertEqual([task.task_id for task in dag.topological_sort()], ["check_webhook_health", "check_subscription_active", "check_recent_deliveries"])
        self.assertEqual(dag.task_dict["check_subscription_active"].upstream_task_ids, {"check_webhook_health"})
        tasks = generator.build_workflow_definition("healthcare_realtime_ingestion")["healthcare_realtime_ingestion"]["tasks"]
        self.assertEqual(tasks["check_webhook_health"]["op_kwargs"], {"stage": "development", "aws_region": "example-region-1"})
        self.assertEqual(tasks["check_recent_deliveries"]["python_callable"], "lib.ingestion_health.check_recent_deliveries")

    def test_serverless_definition_preserves_contract_and_normalizes_ecs_families(self) -> None:
        workflow = generator.build_workflow_definition()["healthcare_realtime_pipeline"]
        tasks = workflow["tasks"]

        self.assertEqual(workflow["schedule"], "0 2 * * *")
        self.assertEqual(workflow["start_date"], "2099-01-01T00:00:00+00:00")
        self.assertEqual(workflow["max_active_runs"], 1)
        self.assertEqual(tasks["run_dbt_build"]["task_definition"], "healthcare_realtime_dbt")
        self.assertEqual(tasks["run_soda_checks"]["task_definition"], "healthcare_realtime_soda")
        self.assertEqual(tasks["run_great_expectations"]["task_definition"], "healthcare_realtime_soda")
        self.assertEqual(tasks["run_ml_scoring"]["task_definition"], "healthcare_realtime_dbt")
        self.assertEqual(
            tasks["run_dbt_build"]["overrides"]["containerOverrides"][0]["command"][-3:], ["--exclude", "ml_predictions_serving", "ml_predictions_latest"]
        )
        self.assertEqual(tasks["run_ml_scoring"]["overrides"]["containerOverrides"][0]["command"], ["score-ml", "--publish-s3"])
        self.assertEqual(
            tasks["run_great_expectations"]["overrides"],
            {"containerOverrides": [{"name": "soda", "command": ["python", "/app/validate_processed_observations.py"]}]},
        )
        self.assertEqual(tasks["run_dbt_build"]["dependencies"], ["extract_cohort_reference"])
        self.assertEqual(tasks["extract_cohort_reference"]["task_definition"], "healthcare_realtime_fhir_setup")
        self.assertEqual(
            tasks["extract_cohort_reference"]["overrides"],
            {"containerOverrides": [{"name": "fhir_setup", "command": ["python", "-m", "jobs.fhir_setup.task", "reference"]}]},
        )
        dbt_command = tasks["run_dbt_build"]["overrides"]["containerOverrides"][0]["command"]
        self.assertEqual(dbt_command[dbt_command.index("--vars") + 1], "{cohort_reference_enabled: true}")
        self.assertEqual(tasks["refresh_prediction_models"]["dependencies"], ["run_ml_scoring"])
        self.assertEqual(tasks["run_soda_checks"]["dependencies"], ["refresh_prediction_models"])
        self.assertEqual(tasks["validate_processed_data"]["op_kwargs"]["openlineage_url"], "https://lineage.example.com")

    def test_task_definition_normalization_accepts_family_revision_and_arn(self) -> None:
        self.assertEqual(generator.normalize_task_definition("family"), "family")
        self.assertEqual(generator.normalize_task_definition("family:12"), "family")
        self.assertEqual(generator.normalize_task_definition("arn:aws:ecs:example-region-1:111111111111:task-definition/family:12"), "family")

    def test_serverless_start_date_rejects_missing_naive_and_past_values(self) -> None:
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ValueError, "is required"):
            generator.serverless_start_date()

        for value, message in (("2099-01-01T00:00:00", "timezone"), ("2020-01-01T00:00:00+00:00", "future")):
            with self.subTest(value=value), patch.dict(os.environ, {"MWAA_SERVERLESS_START_DATE": value}), self.assertRaisesRegex(ValueError, message):
                generator.serverless_start_date()

    def test_contract_validation_rejects_unsupported_dag_and_task_settings(self) -> None:
        dag = SimpleNamespace(catchup=False, max_active_runs=1, default_args={"depends_on_past": False}, schedule=None)
        with self.assertRaisesRegex(ValueError, "requires a schedule"):
            generator.validate_dag_contract(dag)

        callbacks = {name: None for name in ("on_execute_callback", "on_retry_callback", "on_skipped_callback", "on_success_callback", "on_failure_callback")}
        task = SimpleNamespace(task_id="unsupported_callback", depends_on_past=False, **{**callbacks, "on_failure_callback": object()})
        with self.assertRaisesRegex(ValueError, "on_failure_callback"):
            generator.validate_task_contract(task)

        with self.assertRaisesRegex(TypeError, "Unsupported task type"):
            generator.serialize_task(object())

    # The generated-file check that local runs and CI share (validate_generated_workflow.py). Failure modes:
    # 1. The committed check drifts from the DAG (CI on 0586fc0): the file must equal the DAG's current definition.
    # 2. A deployment value leaks into the shareable file: account IDs, ARNs and task revisions are rejected.
    def test_a_freshly_generated_workflow_passes_the_shared_check(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            for name in generator.WORKFLOWS:
                path = Path(scratch) / f"{name}.yaml"
                path.write_text(yaml.safe_dump(generator.build_workflow_definition(name), sort_keys=False), encoding="utf-8")

                self.assertEqual(validator.problems(path), [])

    def test_a_stale_or_leaking_workflow_fails_the_shared_check(self) -> None:
        definition = generator.build_workflow_definition()
        stale = {
            name: {**workflow, "tasks": {key: value for key, value in workflow["tasks"].items() if key != "extract_cohort_reference"}}
            for name, workflow in definition.items()
        }
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / f"{generator.PIPELINE}.yaml"
            path.write_text(yaml.safe_dump(stale, sort_keys=False), encoding="utf-8")
            self.assertTrue(any("does not match" in problem for problem in validator.problems(path)))

            path.write_text(
                yaml.safe_dump(definition, sort_keys=False) + "# arn:aws:ecs:example-region-1:111111111111:task-definition/healthcare_realtime_dbt:42\n",
                encoding="utf-8",
            )
            found = validator.problems(path)
            for expected in ("account ID", "ARN", "task revision"):
                self.assertTrue(any(expected in problem for problem in found), f"expected a problem naming {expected}: {found}")


if __name__ == "__main__":
    unittest.main()
