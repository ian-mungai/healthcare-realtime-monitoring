"""First-iteration scenarios: realtime (E2 to E4), access (E5) and rejection (part of E7). See docs/e2e-test-plan.md."""

from __future__ import annotations

import base64
import json
import time
import uuid
from datetime import UTC, datetime, timedelta

import requests
import websocket

from e2e.context import Context, PatientListener, wait_until
from e2e.report import Blocked, Report

LIVE_VITALS = ("heart_rate", "spo2", "respiratory_rate")
SIMULATOR_CYCLES = 3
TASK_DEADLINE_SECONDS = 300


def positions(context: Context, patient_ids: list[str]) -> str:
    """Name patients by cohort position (1 to 10), never by identifier."""
    return ", ".join(str(context.patient_ids.index(patient_id) + 1) for patient_id in patient_ids) or "none"


def is_newer(after: str | None, before: str | None) -> bool:
    """True when a reading exists after the run and is later than the one before it (ISO-8601 UTC strings)."""
    return after is not None and (before is None or after > before)


def latest_timestamp(context: Context, patient_id: str) -> tuple[str | None, dict]:
    response = context.get(context.vitals_url(patient_id))
    if response.status_code == 404:
        return None, {}
    if response.status_code != 200:
        raise RuntimeError(f"REST read returned HTTP {response.status_code}")
    body = response.json()
    return body.get("event_timestamp"), body


def realtime(context: Context, report: Report) -> None:
    """One simulator run must reach DynamoDB, the REST API and WebSocket subscribers for every patient."""
    report.parameters = {"patients": len(context.patient_ids), "simulator_cycles": SIMULATOR_CYCLES, "task_deadline_seconds": TASK_DEADLINE_SECONDS}
    ecs = context.client("ecs")
    cluster = context.output("hapi_ecs_cluster_name")
    family = context.output("vitals_simulator_task_definition_family")
    running = ecs.list_tasks(cluster=cluster, family=family)["taskArns"]
    if running:
        raise Blocked("a vitals simulator task is already running; stop it so this run's updates can be attributed")
    baseline = {patient_id: latest_timestamp(context, patient_id)[0] for patient_id in context.patient_ids}
    listener = PatientListener(context)
    task_arn = None
    try:
        listener.start()
        report.check(
            "WebSocket subscriptions",
            "a signed connection opens for every patient",
            f"{len(listener.opened)} of {len(context.patient_ids)} opened",
            len(listener.opened) == len(context.patient_ids),
        )
        started = datetime.now(UTC)
        result = ecs.run_task(
            cluster=cluster,
            taskDefinition=family,
            launchType="FARGATE",
            count=1,
            startedBy="healthcare-realtime-e2e",
            networkConfiguration={
                "awsvpcConfiguration": {
                    "subnets": list(context.output("private_subnet_ids")),
                    "securityGroups": [context.output("vitals_simulator_security_group_id")],
                    "assignPublicIp": "DISABLED",
                }
            },
            overrides={"containerOverrides": [{"name": "vitals_simulator", "environment": [{"name": "SIMULATOR_MAX_CYCLES", "value": str(SIMULATOR_CYCLES)}]}]},
        )
        if not result.get("tasks"):
            reasons = "; ".join(failure.get("reason", "unknown") for failure in result.get("failures", []))
            raise RuntimeError(f"the simulator task did not start: {reasons or 'no reason given'}")
        task_arn = result["tasks"][0]["taskArn"]
        ecs.get_waiter("tasks_stopped").wait(cluster=cluster, tasks=[task_arn], WaiterConfig={"Delay": 6, "MaxAttempts": TASK_DEADLINE_SECONDS // 6})
        task = ecs.describe_tasks(cluster=cluster, tasks=[task_arn])["tasks"][0]
        exit_code = task["containers"][0].get("exitCode")
        report.check("Simulator task", "exits 0 after its cycles", f"exit code {exit_code}", exit_code == 0)
        task_arn = None
        report.evidence["simulator_run_seconds"] = round((datetime.now(UTC) - started).total_seconds())

        latest = {patient_id: latest_timestamp(context, patient_id) for patient_id in context.patient_ids}
        stale = [p for p in context.patient_ids if not is_newer(latest[p][0], baseline[p])]
        report.check(
            "REST freshness", "every patient's latest reading is newer than before the run", f"not updated: patients {positions(context, stale)}", not stale
        )
        missing = [p for p in context.patient_ids if any(latest[p][1].get(field) is None for field in LIVE_VITALS)]
        report.check("REST fields", f"{', '.join(LIVE_VITALS)} present for every patient", f"missing for patients {positions(context, missing)}", not missing)
        wait_until(lambda: all(listener.counts.values()), 30)
        silent = [p for p, count in listener.counts.items() if not count]
        report.check("WebSocket delivery", "at least one message per patient", f"no message for patients {positions(context, silent)}", not silent)
        report.evidence["websocket_messages_per_patient"] = sorted(listener.counts.values())
        report.evidence["websocket_errors"] = sorted(set(listener.errors.values()))
    finally:
        listener.close()
        if task_arn:
            ecs.stop_task(cluster=cluster, task=task_arn, reason="E2E run ended early")


def access(context: Context, report: Report) -> None:
    """Unauthenticated and unauthorized requests must be refused for the intended reason."""
    patient_id = context.patient_ids[0]
    unsigned = context.get(context.vitals_url(patient_id), signed=False)
    report.check("Unsigned REST read", "HTTP 403 from IAM authorization", f"HTTP {unsigned.status_code}", unsigned.status_code == 403)

    outsider = f"e2e-not-in-cohort-{uuid.uuid4().hex[:8]}"
    denied = context.get(context.vitals_url(outsider))
    reason = denied.json().get("message", "") if denied.headers.get("content-type", "").startswith("application/json") else ""
    report.check(
        "Signed read outside the cohort",
        "HTTP 403 with 'Access to this patient is not authorized'",
        f"HTTP {denied.status_code}, message {'matches' if reason == 'Access to this patient is not authorized' else 'differs'}",
        denied.status_code == 403 and reason == "Access to this patient is not authorized",
    )

    health = context.get(str(context.output("fhir_webhook_health_url")), signed=False)
    wrong = requests.get(str(context.output("fhir_webhook_health_url")), headers={"X-Webhook-Secret": uuid.uuid4().hex}, timeout=15)
    detail = wrong.json().get("detail", "") if wrong.headers.get("content-type", "").startswith("application/json") else ""
    report.check("Webhook without a secret", "HTTP 401", f"HTTP {health.status_code}", health.status_code == 401)
    report.check(
        "Webhook with a wrong secret",
        "HTTP 401 with 'Invalid webhook secret'",
        f"HTTP {wrong.status_code}, detail {'matches' if detail == 'Invalid webhook secret' else 'differs'}",
        wrong.status_code == 401 and detail == "Invalid webhook secret",
    )

    try:
        connection = websocket.create_connection(context.websocket_url(patient_id), timeout=15)
        connection.close()
        refused, observed = False, "connection opened"
    except websocket.WebSocketBadStatusException as error:
        refused, observed = error.status_code in (401, 403), f"handshake refused with HTTP {error.status_code}"
    report.check("Unsigned WebSocket connection", "refused during the handshake with 401 or 403", observed, refused)
    report.not_run("Principal outside the access policy", "HTTP 403", "needs a second AWS identity; not configured")


def rejection(context: Context, report: Report) -> None:
    """A permanently invalid record is rejected and counted, not retried or replayed."""
    sqs, kinesis, cloudwatch = context.client("sqs"), context.client("kinesis"), context.client("cloudwatch")
    queues = {"failure queue": context.output("realtime_failure_queue_url"), "replay dead-letter queue": context.output("realtime_replay_dlq_url")}

    def depth(url: str) -> int:
        attributes = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"])[
            "Attributes"
        ]
        return int(attributes["ApproximateNumberOfMessages"]) + int(attributes["ApproximateNumberOfMessagesNotVisible"])

    before = {name: depth(url) for name, url in queues.items()}
    if any(before.values()):
        raise Blocked("a failure queue already holds messages; inspect and drain it before this run")
    start = datetime.now(UTC) - timedelta(minutes=1)
    observation_id = f"e2e-rejection-{uuid.uuid4().hex[:12]}"
    record = {"schema_version": "0.0-e2e", "observation_id": observation_id, "patient_id": "e2e-rejection", "source": "load_test"}
    kinesis.put_record(StreamName=context.output("load_test_kinesis_stream_name"), Data=json.dumps(record).encode(), PartitionKey=observation_id)
    report.parameters = {"record": "unsupported schema_version on the isolated load-test stream"}

    def rejected_count() -> float:
        points = cloudwatch.get_metric_statistics(
            Namespace="HealthcareRealtime/Live",
            MetricName="PermanentRecordsRejected",
            StartTime=start,
            EndTime=datetime.now(UTC) + timedelta(minutes=1),
            Period=60,
            Statistics=["Sum"],
        )["Datapoints"]
        return sum(point["Sum"] for point in points)

    counted = wait_until(lambda: rejected_count() >= 1, 300, 15)
    report.check("Rejection counted", "PermanentRecordsRejected counts the record within 5 minutes", f"count {rejected_count():.0f}", counted)
    time.sleep(30)
    after = {name: depth(url) for name, url in queues.items()}
    for name, count in after.items():
        report.check(f"Empty {name}", "no message, because a permanent error is not retried", f"{count} messages", count == 0)
    report.evidence["record_bytes_base64_length"] = len(base64.b64encode(json.dumps(record).encode()))


SCENARIOS = {
    "realtime": (
        realtime,
        "E2 to E4: a simulator run reaches DynamoDB, the REST API and WebSocket subscribers for every patient.",
        "Checks one short simulator run; blood pressure cadence, sustained load and the analytical path are other scenarios.",
    ),
    "access": (
        access,
        "E5: unauthenticated and unauthorized requests are refused for the intended reason.",
        "A principal outside the access policy needs a second AWS identity and is reported as not run.",
    ),
    "rejection": (
        rejection,
        "E7, first part: a permanently invalid record is rejected and counted, not retried or replayed.",
        "The transient-failure replay path is not exercised; it needs a controlled fault and a decision on how to inject one.",
    ),
}
