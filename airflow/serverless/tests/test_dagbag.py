"""DagBag import test: every DAG file imports cleanly and every declared task belongs to a DAG and is wired into it."""

from __future__ import annotations

import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from airflow.dag_processing.dagbag import DagBag

DAG_FOLDER = Path(__file__).resolve().parents[2] / "dags"
TASK_ID = re.compile(r"""task_id\s*=\s*["']([\w.-]+)["']""")
# Placeholder deployment values: the DAG reads them at import time and no AWS call happens while it is parsed.
ENVIRONMENT = {
    "RAW_BUCKET": "ci-project-data-bucket",
    "RAW_PREFIX": "raw/example/",
    "GLUE_JOB_NAME": "example-glue-job",
    "AIRFLOW_PIPELINE_SCHEDULE": "0 2 * * *",
    "DBT_ECS_TASK_DEFINITION": "healthcare_realtime_dbt",
    "SODA_ECS_TASK_DEFINITION": "healthcare_realtime_soda",
    "DATA_JOBS_ECS_CLUSTER": "healthcare-realtime-data-jobs",
    "AWS_REGION": "example-region-1",
    "PROJECT_NAME": "example-project",
    "DATA_BUCKET_NAME": "ci-project-data-bucket",
    "ATHENA_SOURCE_DATABASE": "example_source",
    "ATHENA_PROCESSED_TABLE": "example_processed",
    "ATHENA_WORKGROUP": "example-workgroup",
    "ATHENA_RESULTS_S3_URI": "s3://ci-project-data-bucket/athena-results/",
    "OPENLINEAGE_URL": "https://lineage.example.com",
}


class DagBagTests(unittest.TestCase):
    def setUp(self) -> None:
        environment = patch.dict(os.environ, ENVIRONMENT, clear=False)
        environment.start()
        self.addCleanup(environment.stop)
        self.dagbag = DagBag(dag_folder=str(DAG_FOLDER))

    def test_every_dag_file_imports_without_errors(self) -> None:
        self.assertEqual(self.dagbag.import_errors, {})
        self.assertIn("healthcare_realtime_pipeline", self.dagbag.dags)

    def test_every_declared_task_belongs_to_a_dag(self) -> None:
        declared = {task_id for path in DAG_FOLDER.rglob("*.py") for task_id in TASK_ID.findall(path.read_text())}
        used = {task.task_id for dag in self.dagbag.dags.values() for task in dag.tasks}
        self.assertEqual(declared - used, set())

    def test_every_task_is_wired_into_its_dag(self) -> None:
        for dag in self.dagbag.dags.values():
            if len(dag.tasks) < 2:
                continue
            unwired = sorted(task.task_id for task in dag.tasks if not task.upstream_task_ids and not task.downstream_task_ids)
            self.assertEqual(unwired, [], f"{dag.dag_id} has tasks with no upstream or downstream task")


if __name__ == "__main__":
    unittest.main()
