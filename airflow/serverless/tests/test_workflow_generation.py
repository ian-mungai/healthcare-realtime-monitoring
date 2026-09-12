from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import generate_healthcare_realtime_pipeline as generator


class WorkflowGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = patch.dict(
            os.environ,
            {
                "RAW_BUCKET": "ci-project-data-bucket",
                "AIRFLOW__DBT__ECS_SECURITY_GROUP": "sg-ci-placeholder",
                "AIRFLOW__DBT__ECS_SUBNETS": "subnet-ci-a,subnet-ci-b",
                "AIRFLOW__SODA__ECS_SECURITY_GROUP": "sg-ci-placeholder",
                "AIRFLOW__SODA__ECS_SUBNETS": "subnet-ci-a,subnet-ci-b",
                "DBT_ECS_TASK_DEFINITION": ("arn:aws:ecs:example-region-1:111111111111:task-definition/healthcare_realtime_dbt:42"),
                "SODA_ECS_TASK_DEFINITION": "healthcare_realtime_soda:17",
                "DATA_JOBS_ECS_CLUSTER": "healthcare-realtime-data-jobs",
                "MWAA_SERVERLESS_START_DATE": "2099-01-01T00:00:00+00:00",
                "OPENLINEAGE_URL": "https://lineage.example.com",
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
        self.assertEqual(len(dag.tasks), 7)
        self.assertEqual(dag.task_dict["run_great_expectations"].upstream_task_ids, {"validate_processed_data"})
        self.assertEqual(dag.task_dict["run_dbt_build"].upstream_task_ids, {"run_great_expectations"})
        self.assertEqual(dag.task_dict["run_soda_checks"].upstream_task_ids, {"run_dbt_build"})

    def test_serverless_definition_preserves_contract_and_normalizes_ecs_families(self) -> None:
        workflow = generator.build_workflow_definition()["healthcare_realtime_pipeline"]
        tasks = workflow["tasks"]

        self.assertEqual(workflow["schedule"], "0 2 * * *")
        self.assertEqual(workflow["start_date"], "2099-01-01T00:00:00+00:00")
        self.assertEqual(workflow["max_active_runs"], 1)
        self.assertEqual(tasks["run_dbt_build"]["task_definition"], "healthcare_realtime_dbt")
        self.assertEqual(tasks["run_soda_checks"]["task_definition"], "healthcare_realtime_soda")
        self.assertEqual(tasks["run_great_expectations"]["task_definition"], "healthcare_realtime_soda")
        self.assertEqual(
            tasks["run_great_expectations"]["overrides"],
            {"containerOverrides": [{"name": "soda", "command": ["python", "/app/validate_processed_observations.py"]}]},
        )
        self.assertEqual(tasks["run_dbt_build"]["dependencies"], ["run_great_expectations"])
        self.assertEqual(tasks["validate_processed_data"]["op_kwargs"]["openlineage_url"], "https://lineage.example.com")

    def test_task_definition_normalization_accepts_family_revision_and_arn(self) -> None:
        self.assertEqual(generator.normalize_task_definition("family"), "family")
        self.assertEqual(generator.normalize_task_definition("family:12"), "family")
        self.assertEqual(generator.normalize_task_definition("arn:aws:ecs:example-region-1:111111111111:task-definition/family:12"), "family")

    def test_serverless_start_date_rejects_missing_naive_and_past_values(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "is required"):
                generator.serverless_start_date()

        for value, message in (("2099-01-01T00:00:00", "timezone"), ("2020-01-01T00:00:00+00:00", "future")):
            with self.subTest(value=value), patch.dict(os.environ, {"MWAA_SERVERLESS_START_DATE": value}):
                with self.assertRaisesRegex(ValueError, message):
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


if __name__ == "__main__":
    unittest.main()
