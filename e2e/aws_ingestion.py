"""Check the ingestion health workflow on AWS: one run of its three webhook checks succeeds.

Usage: python -m e2e.aws_ingestion [--env-file PATH]

Run it after the application stage is applied and the cohort subscription is registered (run_fhir_setup.sh). It starts
one run of the MWAA Serverless ingestion workflow (airflow/dags/healthcare_realtime_ingestion.py), waits for it to end
and checks that the run and each of its three tasks succeeded: the webhook answers healthy, HAPI's subscription to it is
active and the webhook Lambda had no errors in the last 30 minutes. Every run writes report.json and report.md under
artifacts/e2e/aws_ingestion/, passed, failed or blocked.

Failure modes (written before the code):

1. The run is started twice by a retried request: the start uses a client token, so a retry joins the same run.
2. The check waits forever on a run that hangs: it stops after RUN_SECONDS and reports the last state.
3. The run succeeds with a task missing or skipped: each of the three tasks must be present and successful.
4. A task's earlier failed try hides its final result, or a try number is read as part of the name: task instance IDs
   end in the try number (ex_<run>_<task>_<try>), and only each task's last try counts.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from e2e.context import ROOT, Context, load_context, wait_until
from e2e.report import Report

TASKS = ("check_webhook_health", "check_subscription_active", "check_recent_deliveries")
RUN_SECONDS = 900
TERMINAL = {"SUCCESS", "FAILED", "TIMEOUT", "STOPPED"}
PURPOSE = "The ingestion health workflow runs its three webhook checks on AWS and every one succeeds."
LIMITS = "Checks one run against a healthy deployment; it does not break the webhook to prove that a check fails, which the unit tests cover."
REPRODUCE = "Apply the application stage, register the subscription, then run `.venv/bin/python -m e2e.aws_ingestion`."


def task_states(client: Any, workflow_arn: str, run_id: str) -> dict[str, str]:
    """Each task's status on its last try, by task name."""
    tries: dict[str, tuple[int, str]] = {}
    arguments: dict[str, Any] = {"WorkflowArn": workflow_arn, "RunId": run_id}
    while True:
        page = client.list_task_instances(**arguments)
        for instance in page.get("TaskInstances", []):
            name, _, attempt = instance["TaskInstanceId"].rpartition("_")
            task = next((task for task in TASKS if name.endswith(task)), name)
            number = int(attempt) if attempt.isdigit() else 0
            if task not in tries or number >= tries[task][0]:
                tries[task] = (number, instance["Status"])
        if not page.get("NextToken"):
            return {task: status for task, (_, status) in tries.items()}
        arguments["NextToken"] = page["NextToken"]


def run(report: Report, context: Context) -> None:
    workflow_arn = context.output("mwaa_ingestion_workflow_arn")
    client = context.client("mwaa-serverless")
    run_id = client.start_workflow_run(WorkflowArn=workflow_arn, ClientToken=str(uuid.uuid4()))["RunId"]
    report.parameters = {"workflow": str(workflow_arn).rsplit("/", 1)[-1], "run_id": run_id}

    def state() -> str:
        return client.get_workflow_run(WorkflowArn=workflow_arn, RunId=run_id)["RunDetail"]["RunState"]

    wait_until(lambda: state() in TERMINAL, RUN_SECONDS, interval_seconds=10)
    final = state()
    report.check("Ingestion workflow run", "SUCCESS", final, final == "SUCCESS")
    states = task_states(client, workflow_arn, run_id)
    for task in TASKS:
        observed = states.get(task, "absent")
        report.check(f"Task {task}", "SUCCESS", observed, observed == "SUCCESS")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--env-file", type=Path, default=Path(os.getenv("PROJECT_ENV_FILE") or ROOT / ".env"))
    args = parser.parse_args(argv)
    report = Report(scenario="aws_ingestion", purpose=PURPOSE, limits=LIMITS, reproduce=REPRODUCE)
    error: BaseException | None = None
    try:
        run(report, load_context(args.env_file))
    except Exception as failure:
        error = failure
    report.finish(error)
    folder = report.write()
    sys.stdout.write(f"aws_ingestion: {report.status} ({folder.relative_to(ROOT)}/report.md)\n")
    return 0 if report.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
