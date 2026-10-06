"""First-iteration scenarios: realtime (E2 to E4), access (E5) and rejection (part of E7)."""

from __future__ import annotations

import base64
import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import requests
import websocket
from botocore.exceptions import BotoCoreError, ClientError

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


REPLAY_DEADLINE_SECONDS = 600
REPLAY_POLICY_DEADLINE_SECONDS = 300
REPLAY_CLEANUP_DEADLINE_SECONDS = 120
REPLAY_CLEANUP_QUIET_SECONDS = 30


def invoke_replay_probe(lam: Any, function_name: str, patient_id: str, observation_id: str) -> tuple[bool, bool]:
    """Invoke the deployed processor synchronously; return healthy-write and specific UpdateItem-denial evidence.

    The synthetic probe bypasses Kinesis and never establishes replay coverage. The returned log tail is inspected in
    memory only. A partial-batch failure counts as an injected failure only with the matching AccessDenied log.
    """
    payload = {
        "schema_version": "1.1",
        "observation_id": observation_id,
        "patient_id": patient_id,
        "encounter_id": observation_id,
        "source": "e2e_replay",
        "event_timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "heart_rate": 72,
    }
    event = {"Records": [{"kinesis": {"sequenceNumber": "1", "data": base64.b64encode(json.dumps(payload).encode()).decode()}}]}
    result = lam.invoke(FunctionName=function_name, InvocationType="RequestResponse", LogType="Tail", Payload=json.dumps(event).encode())
    response = result.get("Payload")
    if response is None:
        raise Blocked("the processor probe did not return a handler payload")
    try:
        if result.get("StatusCode") != 200 or result.get("FunctionError"):
            raise Blocked("the processor probe did not return a valid handler response; inspect its service logs")
        body = json.loads(response.read())
        tail = base64.b64decode(result.get("LogResult", "")).decode(errors="replace")
    except (ValueError, TypeError):
        raise Blocked("the processor probe returned malformed response or log evidence") from None
    finally:
        response.close()
    failures = body.get("batchItemFailures") if isinstance(body, dict) else None
    if failures not in ([], [{"itemIdentifier": "1"}]):
        raise Blocked("the processor probe returned unexpected partial-batch results")
    denied = failures == [{"itemIdentifier": "1"}] and any(
        "Failed Kinesis record 1:" in line and "AccessDeniedException" in line and "when calling the UpdateItem operation" in line for line in tail.splitlines()
    )
    if failures and not denied:
        raise Blocked("the processor probe failed without the intended UpdateItem access denial; inspect its service logs")
    return not failures, denied


def replay(context: Context, report: Report) -> None:
    """Prove a patient-specific write denial before submitting the main-stream record and checking its one replay.

    Direct processor probes establish the failure and its removal. Main-stream processing, retry and terminal delivery
    remain the real E2E boundary. Cleanup checks run independently and never include another patient's records.
    """
    iam, lam, sqs, kinesis = context.client("iam"), context.client("lambda"), context.client("sqs"), context.client("kinesis")
    dynamodb = context.client("dynamodb")
    queues = {"failure queue": context.output("realtime_failure_queue_url"), "replay dead-letter queue": context.output("realtime_replay_dlq_url")}
    table_name, table_arn = context.output("latest_vitals_table_name"), context.output("latest_vitals_table_arn")
    function_name = context.output("realtime_processor_lambda_name")
    try:
        configuration = lam.get_function_configuration(FunctionName=function_name)
        environment = configuration.get("Environment", {}).get("Variables", {})
        if environment.get("LATEST_VITALS_TABLE") != table_name or not environment.get("IDEMPOTENCY_TABLE"):
            raise Blocked("processor table configuration differs from the selected deployment outputs")
        table = dynamodb.describe_table(TableName=table_name)["Table"]
        if table.get("TableArn") != table_arn or table.get("KeySchema") != [{"AttributeName": "patient_id", "KeyType": "HASH"}]:
            raise Blocked("latest-vitals table ARN or patient partition key differs from the selected deployment")
        ecs = context.client("ecs")
        if ecs.list_tasks(cluster=context.output("hapi_ecs_cluster_name"), family=context.output("vitals_simulator_task_definition_family"))["taskArns"]:
            raise Blocked("a simulator is running; stop it before the isolated replay check")
    except (ClientError, BotoCoreError):
        raise Blocked("an AWS request stopped replay preflight; inspect configuration and access before injecting a failure") from None
    role_arn = configuration["Role"]
    role_name = role_arn.rsplit("/", 1)[-1]
    run = uuid.uuid4().hex[:12]
    patient_id, observation_id, policy_name = f"e2e-replay-{run}", f"e2e-replay-{run}", f"healthcare_realtime_e2e_replay_{run}"
    report.parameters = {
        "deadline_seconds": REPLAY_DEADLINE_SECONDS,
        "policy_deadline_seconds": REPLAY_POLICY_DEADLINE_SECONDS,
        "patient": "one synthetic patient outside the cohort",
        "preflight": "policy readback, simulation and actual processor denial",
    }
    observation_ids: set[str] = set()
    policy_attempted = False
    baseline_ok = False
    submission_attempted = False
    submission_accepted = False
    found: dict = {}

    def depth(url: str) -> int:
        attributes = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"])[
            "Attributes"
        ]
        return int(attributes["ApproximateNumberOfMessages"]) + int(attributes["ApproximateNumberOfMessagesNotVisible"])

    try:
        if any(depth(url) for url in queues.values()):
            raise Blocked("a failure queue already holds messages; inspect it before this run")
    except (ClientError, BotoCoreError):
        raise Blocked("failure queue state could not be read; no failure was injected") from None

    def patient_item() -> dict | None:
        return dynamodb.get_item(TableName=table_name, Key={"patient_id": {"S": patient_id}}, ConsistentRead=True).get("Item")

    def probe() -> tuple[bool, bool]:
        identifier = f"e2e-probe-{run}-{len(observation_ids)}"
        observation_ids.add(identifier)
        return invoke_replay_probe(lam, function_name, patient_id, identifier)

    deny: dict[str, Any] = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "E2EReplayBlockOnePatient",
                "Effect": "Deny",
                "Action": ["dynamodb:PutItem", "dynamodb:UpdateItem"],
                "Resource": table_arn,
                "Condition": {"ForAnyValue:StringEquals": {"dynamodb:LeadingKeys": [patient_id]}},
            }
        ],
    }

    def policy_document() -> dict | None:
        try:
            return iam.get_role_policy(RoleName=role_name, PolicyName=policy_name).get("PolicyDocument")
        except ClientError as error:
            if error.response["Error"]["Code"] == "NoSuchEntity":
                return None
            raise

    def block_effective() -> bool:
        if policy_document() != deny:
            return False
        simulation = iam.simulate_principal_policy(
            PolicySourceArn=role_arn,
            ActionNames=["dynamodb:PutItem", "dynamodb:UpdateItem"],
            ResourceArns=[table_arn],
            ContextEntries=[{"ContextKeyName": "dynamodb:LeadingKeys", "ContextKeyValues": [patient_id], "ContextKeyType": "stringList"}],
        )
        decisions = {entry["EvalActionName"]: entry["EvalDecision"] for entry in simulation.get("EvaluationResults", [])}
        if any(decisions.get(action) != "explicitDeny" for action in deny["Statement"][0]["Action"]):
            return False
        healthy, denied = probe()
        absent = not patient_item()
        if healthy:
            dynamodb.delete_item(TableName=table_name, Key={"patient_id": {"S": patient_id}})
        return denied and absent

    def terminal_message() -> dict | None:
        messages = sqs.receive_message(QueueUrl=queues["replay dead-letter queue"], MaxNumberOfMessages=10, VisibilityTimeout=5, WaitTimeSeconds=5)
        for message in messages.get("Messages", []):
            try:
                body = json.loads(message["Body"])
            except (ValueError, TypeError):
                continue
            if isinstance(body, dict) and body.get("partition_key") == observation_id:
                return {"handle": message["ReceiptHandle"], "body": body}
        return None

    try:
        healthy, _denied = probe()
        baseline_ok = healthy and bool(patient_item())
        report.check("Processor baseline", "a fresh synthetic probe writes before the Deny", "written" if baseline_ok else "not written", baseline_ok)
        if not baseline_ok:
            raise Blocked("the processor baseline write failed before the injected policy; inspect the existing configuration")
        dynamodb.delete_item(TableName=table_name, Key={"patient_id": {"S": patient_id}})
        policy_attempted = True
        iam.put_role_policy(RoleName=role_name, PolicyName=policy_name, PolicyDocument=json.dumps(deny))
        blocked = wait_until(block_effective, REPLAY_POLICY_DEADLINE_SECONDS, 10)
        report.check(
            "Injected write denial", "the processor returns UpdateItem AccessDenied and leaves no row", "confirmed" if blocked else "not confirmed", blocked
        )
        if not blocked:
            raise Blocked("the patient-specific write block did not take effect within five minutes; no main-stream record was submitted")
        payload = {
            "schema_version": "1.1",
            "observation_id": observation_id,
            "patient_id": patient_id,
            "encounter_id": f"e2e-encounter-{run}",
            "source": "e2e_replay",
            "event_timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "heart_rate": 72,
        }
        observation_ids.add(observation_id)
        submission_attempted = True
        kinesis.put_record(StreamName=context.output("kinesis_stream_name"), Data=json.dumps(payload).encode(), PartitionKey=observation_id)
        submission_accepted = True
        terminal_found = wait_until(lambda: bool(found.update(terminal_message() or {}) or found), REPLAY_DEADLINE_SECONDS, 15)
        body = found.get("body", {})
        replayed = json.loads(base64.b64decode(body.get("data_base64", "")) or b"{}").get("_replay_attempt") if body else None
        report.check(
            "Terminal record", "the record reaches the replay dead-letter queue within 10 minutes", "found" if terminal_found else "not found", terminal_found
        )
        report.check(
            "Replayed once",
            "the parked record carries _replay_attempt 1",
            "_replay_attempt 1" if type(replayed) is int and replayed == 1 else "missing or unexpected replay count",
            type(replayed) is int and replayed == 1,
        )
        reason_matches = "replay limit reached" in str(body.get("reason", "")).lower()
        report.check("Reason", "the dead-letter body says the replay limit was reached", "matches" if reason_matches else "differs", reason_matches)
        absent = not patient_item()
        report.check("No write while blocked", "no latest-vitals item for the synthetic patient", "absent" if absent else "present", absent)
    except (ClientError, BotoCoreError):
        raise Blocked("an AWS prerequisite or service request stopped replay verification; inspect access and service logs") from None
    finally:
        policy_removed = not policy_attempted
        if policy_attempted:
            try:
                try:
                    iam.delete_role_policy(RoleName=role_name, PolicyName=policy_name)
                except ClientError as error:
                    if error.response["Error"]["Code"] != "NoSuchEntity":
                        raise
                policy_removed = wait_until(lambda: policy_document() is None, 30)
            except (ClientError, BotoCoreError):
                policy_removed = False
            report.check("Temporary policy removed", "the run's policy is absent", "absent" if policy_removed else "removal not verified", policy_removed)
        if policy_attempted and policy_removed and baseline_ok:
            try:
                restored = wait_until(lambda: probe()[0] and bool(patient_item()), REPLAY_POLICY_DEADLINE_SECONDS, 10)
            except (Blocked, ClientError, BotoCoreError):
                restored = False
            report.check("Processor write restored", "a fresh probe writes after removing the Deny", "written" if restored else "not verified", restored)
        if submission_attempted:
            try:
                seen_terminal = bool(found.get("handle"))
                quiet_since: float | None = None
                if found.get("handle"):
                    sqs.delete_message(QueueUrl=queues["replay dead-letter queue"], ReceiptHandle=found["handle"])

                def queues_drained() -> bool:
                    nonlocal seen_terminal, quiet_since
                    late_message = terminal_message()
                    if late_message:
                        sqs.delete_message(QueueUrl=queues["replay dead-letter queue"], ReceiptHandle=late_message["handle"])
                        seen_terminal = True
                        quiet_since = None
                    if any(depth(url) for url in queues.values()):
                        quiet_since = None
                        return False
                    if not seen_terminal:
                        return False
                    if quiet_since is None:
                        quiet_since = time.monotonic()
                    return time.monotonic() - quiet_since >= REPLAY_CLEANUP_QUIET_SECONDS

                drained = wait_until(queues_drained, REPLAY_CLEANUP_DEADLINE_SECONDS, 5)
                report.check(
                    "Owned terminal cleanup",
                    "owned terminal removed and both queues stay empty for 30 seconds within the two-minute cleanup window",
                    "confirmed" if drained else "not verified within the cleanup window",
                    drained,
                )
            except (ClientError, BotoCoreError):
                report.check("Queue cleanup", "owned messages removed", "cleanup request failed", False)
        for name, url in queues.items():
            try:
                count = depth(url)
                report.check(f"Empty {name} afterwards", "no messages left by the run", f"{count} messages", count == 0)
            except (ClientError, BotoCoreError):
                report.check(f"Empty {name} afterwards", "no messages left by the run", "read failed", False)
        cleanup_ok = True
        for target, key in [
            (table_name, {"patient_id": {"S": patient_id}}),
            *[(environment["IDEMPOTENCY_TABLE"], {"observation_id": {"S": identifier}}) for identifier in sorted(observation_ids)],
        ]:
            try:
                dynamodb.delete_item(TableName=target, Key=key)
            except (ClientError, BotoCoreError):
                cleanup_ok = False
        try:
            cleanup_ok = not patient_item() and cleanup_ok
        except (ClientError, BotoCoreError):
            cleanup_ok = False
        report.check(
            "Owned rows removed",
            "the patient row is absent and deletion of the run's observation claims is acknowledged",
            "verified" if cleanup_ok else "cleanup not verified",
            cleanup_ok,
        )
        report.evidence["processor_probe_count"] = len(observation_ids) - int(submission_attempted)
        report.evidence["main_stream_submission_attempted"] = submission_attempted
        report.evidence["main_stream_record_submitted"] = submission_accepted
        report.evidence["queue_cleanup_observation_seconds"] = REPLAY_CLEANUP_DEADLINE_SECONDS
        report.evidence["side_effect"] = "main-stream records can reach raw storage through Firehose; direct probes bypass it; raw storage was not checked"


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
        "The transient-failure replay path is the replay scenario.",
    ),
    "replay": (
        replay,
        "E7, second part: a valid record whose write keeps failing is replayed once and parked in the replay dead-letter queue.",
        "Blocks writes for one synthetic patient on the main stream only; load-test stream failures are never replayed.",
    ),
}
