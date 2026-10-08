"""Check the AWS Grafana end to end through an SSM port forward: every panel query runs on Athena.

Usage: python -m e2e.aws_grafana [--env-file PATH]

Run it after the application stage is applied with ENABLE_GRAFANA=true, the Grafana image is pushed and the daily
workflow has built the dbt models. It finds the Grafana task running the service's current task definition, checks that
the task has no public address and no inbound rule, opens an SSM port forward to it with the AWS CLI and its
session-manager-plugin, reads the admin password from Secrets Manager into memory and runs the checks of
e2e.local_grafana: every dashboard is provisioned, every panel query runs through the Athena data source and returns
rows, and the census panel equals a direct Athena count. Every run writes report.json and report.md under
artifacts/e2e/aws_grafana/, passed, failed or blocked.

Failure modes (written before the code):

1. The port forward outlives the run: tools.process.background stops the CLI and its plugin on every exit.
2. The admin password reaches the report, a log or the command line: it is held in memory and sent only to Grafana.
3. The forward never opens (plugin missing, ECS Exec agent not running, permission denied): blocked, with the CLI's
   last output, which names the cause.
4. A task of an earlier deployment answers: only a running task of the service's current task definition is used.
5. Grafana is reachable from outside the VPC: the task must have no public IP and its security groups no inbound rule.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from e2e.context import ROOT, Context, load_context
from e2e.local_grafana import QUERY_RANGE, check_dashboards
from e2e.report import Blocked, Report
from scripts.grafana import render_dashboards as render
from tools.process import background, find_program

CONTAINER = "grafana"
FORWARD_DOCUMENT = "AWS-StartPortForwardingSession"
READY_SECONDS = 90
CENSUS_SQL = "select sum(census) from fact_unit_hourly_census"
PURPOSE = "The AWS Grafana, reached only through an SSM port forward, serves the dashboards and every panel query returns rows from Athena."
LIMITS = (
    "Runs the panel queries through Grafana's query API, not a browser, so it does not check how panels draw. The "
    "dashboards show the synthetic cohort's warehouse; they are not a clinical system. One task, no load."
)
REPRODUCE = (
    "Apply with ENABLE_GRAFANA=true after push_images.sh, let the daily workflow build dbt, install session-manager-plugin, "
    "then run `.venv/bin/python -m e2e.aws_grafana`."
)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def current_task(context: Context, cluster: str, service: str) -> dict[str, Any]:
    """The running task of the service's current task definition, with its Grafana container and ECS Exec agent running."""
    ecs = context.client("ecs")
    services = ecs.describe_services(cluster=cluster, services=[service])["services"]
    if not services:
        raise Blocked(f"ECS service {service} is not in cluster {cluster}")
    definition = services[0]["taskDefinition"]
    arns = ecs.list_tasks(cluster=cluster, serviceName=service, desiredStatus="RUNNING")["taskArns"]
    tasks = ecs.describe_tasks(cluster=cluster, tasks=arns)["tasks"] if arns else []
    for task in tasks:
        if task["taskDefinitionArn"] != definition or task.get("lastStatus") != "RUNNING":
            continue
        container: dict[str, Any] = next((item for item in task["containers"] if item["name"] == CONTAINER), {})
        agents = {agent["name"]: agent.get("lastStatus") for agent in container.get("managedAgents", [])}
        if container.get("runtimeId") and agents.get("ExecuteCommandAgent") == "RUNNING":
            return {**task, "grafana_runtime_id": container["runtimeId"], "service": services[0]}
    raise Blocked(f"no running {service} task of {definition.rsplit('/', 1)[-1]} with its ECS Exec agent running; wait for the deployment")


def check_private(report: Report, context: Context, task: dict[str, Any]) -> None:
    ec2 = context.client("ec2")
    details = {item["name"]: item["value"] for attachment in task.get("attachments", []) for item in attachment.get("details", [])}
    interface = ec2.describe_network_interfaces(NetworkInterfaceIds=[details["networkInterfaceId"]])["NetworkInterfaces"][0]
    public_ip = interface.get("Association", {}).get("PublicIp")
    report.check("Grafana task has no public address", "no public IP", public_ip and "a public IP" or "none", public_ip is None)
    groups = task["service"]["networkConfiguration"]["awsvpcConfiguration"]["securityGroups"]
    inbound = [rule for group in ec2.describe_security_groups(GroupIds=groups)["SecurityGroups"] for rule in group.get("IpPermissions", [])]
    report.check("Grafana security groups allow no inbound traffic", "0 inbound rules", f"{len(inbound)} inbound rules", not inbound)


def athena_census(context: Context) -> float:
    """The census total counted by Athena directly, not through Grafana."""
    rows = context.athena_rows(CENSUS_SQL, render.aws_target().values["ANALYTICS"])
    return float(rows[0][0] or 0)


def wait_ready(url: str, forward: Any) -> None:
    deadline = time.monotonic() + READY_SECONDS
    while time.monotonic() < deadline:
        if forward.poll() is not None:
            output = forward.stdout.read() if forward.stdout else ""
            raise Blocked(f"the SSM port forward exited with {forward.returncode}: {output.strip()[-300:]}")
        try:
            if httpx.get(f"{url}/api/health", timeout=5).status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(2)
    raise Blocked(f"Grafana did not answer through the port forward within {READY_SECONDS} seconds")


def run(report: Report, context: Context) -> None:
    service = context.output("grafana_service_name")
    if not service:
        raise Blocked("Grafana is disabled; set ENABLE_GRAFANA=true, render the configuration and apply")
    if find_program("session-manager-plugin") is None:
        raise Blocked("session-manager-plugin is not installed; the AWS CLI needs it for the port forward")
    cluster = context.output("hapi_ecs_cluster_name")
    task = current_task(context, cluster, service)
    check_private(report, context, task)
    password = context.client("secretsmanager").get_secret_value(SecretId=context.output("grafana_admin_secret_arn"))["SecretString"]
    port = free_port()
    task_id = task["taskArn"].rsplit("/", 1)[-1]
    parameters = json.dumps({"portNumber": [str(context.output("grafana_container_port"))], "localPortNumber": [str(port)]})
    target = f"ecs:{cluster}_{task_id}_{task['grafana_runtime_id']}"
    report.parameters = {"service": service, "task_definition": task["taskDefinitionArn"].rsplit("/", 1)[-1], "range": QUERY_RANGE}
    environment = {**os.environ, "AWS_PROFILE": context.env["AWS_PROFILE"], "AWS_REGION": context.env["AWS_REGION"]}
    args = ["ssm", "start-session", "--target", target, "--document-name", FORWARD_DOCUMENT, "--parameters", parameters]
    with background("aws", args, cwd=ROOT, env=environment) as forward:
        url = f"http://127.0.0.1:{port}"
        wait_ready(url, forward)
        with httpx.Client(base_url=url, auth=("admin", password), timeout=120) as client:
            check_dashboards(report, client, lambda: athena_census(context))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--env-file", type=Path, default=Path(os.getenv("PROJECT_ENV_FILE") or ROOT / ".env"))
    args = parser.parse_args(argv)
    report = Report(scenario="aws_grafana", purpose=PURPOSE, limits=LIMITS, reproduce=REPRODUCE)
    error: BaseException | None = None
    try:
        run(report, load_context(args.env_file))
    except Exception as failure:
        error = failure
    report.finish(error)
    folder = report.write()
    sys.stdout.write(f"aws_grafana: {report.status} ({folder.relative_to(ROOT)}/report.md)\n")
    return 0 if report.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
