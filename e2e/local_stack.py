"""Check the local Docker stack end to end and write its report.

Usage: python -m e2e.local_stack [--env-file PATH]

Start the stack first with scripts/local/local_stack.sh start. The run checks that Postgres holds the HAPI, warehouse
and Grafana databases, that HAPI FHIR stores resources in Postgres and assigns UUID patient IDs, that a repeated
conditional create returns the same patient, that Grafana is healthy and can query the warehouse through its
provisioned data source, that every published port listens on localhost only and that every container runs with the
memory limit planned at start. Every run writes report.json and
report.md under artifacts/e2e/local_stack/, passed, failed or blocked.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

import httpx

from e2e.report import ROOT, Blocked, Report
from scripts.infrastructure.render_project_config import load_environment_file
from tools.process import run_command

COMPOSE_FILE = ROOT / "deploy" / "local" / "compose.yaml"
STACK_ENV_FILE = ROOT / "deploy" / "local" / ".env"
DATABASES = ("hapi", "warehouse", "grafana")
CHECK_IDENTIFIER_SYSTEM = "https://example.org/fhir/NamingSystem/local-stack-check"
CHECK_IDENTIFIER_VALUE = "local-stack-check-patient"
PURPOSE = "The local Docker stack runs Postgres, HAPI FHIR and Grafana together on localhost with UUID patient IDs."
REPRODUCE = "`scripts/local/local_stack.sh start`, then `.venv/bin/python -m e2e.local_stack`."
LIMITS = (
    "Checks one synthetic check patient and a single warehouse query; it does not load the cohort, run dbt or build "
    "dashboards. Local results do not prove AWS behavior."
)


def setting(env: dict[str, str], name: str, default: str | None = None) -> str:
    """A local stack setting from the process environment or the env file, or Blocked naming it."""
    value = os.getenv(name) or env.get(name) or default
    if not value:
        raise Blocked(f"{name} is not set; run scripts/local/local_stack.sh start to generate deploy/local/.env")
    return value


def compose(*args: str) -> str:
    """Run docker compose against the local stack file and return its output, or Blocked when Docker fails."""
    result = run_command("docker", ["compose", "-f", str(COMPOSE_FILE), *args], cwd=ROOT, timeout=60)
    if result.returncode != 0:
        raise Blocked(f"docker compose {args[0]} failed; start the stack with scripts/local/local_stack.sh start")
    return result.stdout


def psql(database: str, query: str) -> str:
    """Run one query as the Postgres superuser inside the container and return the unaligned result."""
    return compose("exec", "-T", "postgres", "psql", "-U", "postgres", "-d", database, "-tAc", query).strip()


def check_ports(report: Report) -> None:
    published = [json.loads(line) for line in compose("ps", "--format", "json").splitlines() if line.strip()]
    addresses = sorted({publisher["URL"] for service in published for publisher in service.get("Publishers") or [] if publisher.get("PublishedPort")})
    report.check("Services running", "3 services running", f"{len(published)} running", len(published) == 3)
    report.check("Ports bound to localhost only", "127.0.0.1 only", ", ".join(addresses) or "none", addresses == ["127.0.0.1"])


def check_memory_limits(report: Report) -> None:
    """Each container has the limit local_stack.sh start planned; a direct `docker compose up` leaves them unlimited."""
    containers = compose("ps", "--quiet").split()
    result = run_command("docker", ["inspect", "--format", "{{.Name}} {{.HostConfig.Memory}}", *containers], cwd=ROOT, timeout=60) if containers else None
    rows = [line.split() for line in (result.stdout if result and result.returncode == 0 else "").splitlines() if line.strip()]
    unlimited = [name.lstrip("/") for name, memory in rows if int(memory) == 0]
    shown = ", ".join(f"{name.lstrip('/').removeprefix('healthcare-realtime-local-')} {int(memory) // 1024**2} MiB" for name, memory in rows)
    report.check("Memory limits planned at start", "every container limited", shown or "none", len(rows) == 3 and not unlimited)


def check_postgres(report: Report) -> None:
    present = set(psql("postgres", "SELECT datname FROM pg_database").split())
    missing = [name for name in DATABASES if name not in present]
    report.check("Postgres databases", "hapi, warehouse and grafana exist", f"missing: {', '.join(missing) or 'none'}", not missing)
    grafana_tables = psql("grafana", "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
    report.check(
        "Grafana keeps its state in Postgres",
        "Grafana tables in the grafana database",
        f"{grafana_tables} tables",
        grafana_tables.isdigit() and int(grafana_tables) > 0,
    )
    reader_can_write = psql("warehouse", "SELECT has_schema_privilege('grafana_reader', 'public', 'CREATE')")
    report.check(
        "Dashboard role is read-only",
        "grafana_reader cannot create warehouse tables",
        "can create" if reader_can_write == "t" else "cannot create",
        reader_can_write == "f",
    )


def check_hapi(report: Report, base_url: str) -> None:
    with httpx.Client(base_url=base_url, headers={"Accept": "application/fhir+json"}, timeout=30) as client:
        metadata = client.get("/metadata")
        version = metadata.json().get("fhirVersion") if metadata.status_code == 200 else None
        report.check("HAPI capability statement", "HTTP 200, FHIR 4.0.1", f"HTTP {metadata.status_code}, FHIR {version}", version == "4.0.1")
        patient = {
            "resourceType": "Patient",
            "identifier": [{"system": CHECK_IDENTIFIER_SYSTEM, "value": CHECK_IDENTIFIER_VALUE}],
            "name": [{"family": "Check", "given": ["Local"]}],
        }
        headers = {"Content-Type": "application/fhir+json", "If-None-Exist": f"identifier={CHECK_IDENTIFIER_SYSTEM}|{CHECK_IDENTIFIER_VALUE}"}
        ids = []
        for _ in range(2):
            response = client.post("/Patient", json=patient, headers=headers)
            ids.append(response.json().get("id") if response.status_code in (200, 201) else None)
    first, second = ids
    report.check("Patient ID format", "server-assigned UUID", "UUID" if is_uuid(first) else "not a UUID", is_uuid(first))
    report.check(
        "Conditional create repeats safely",
        "second create returns the same patient",
        "same" if first and first == second else "different",
        bool(first) and first == second,
    )
    stored = psql("hapi", "SELECT count(*) FROM hfj_resource WHERE res_type = 'Patient'") if first else "0"
    report.check("HAPI stores resources in Postgres", "at least 1 Patient row in the hapi database", f"{stored} rows", stored.isdigit() and int(stored) >= 1)


def check_grafana(report: Report, base_url: str, password: str) -> None:
    with httpx.Client(base_url=base_url, auth=("admin", password), timeout=30) as client:
        health = client.get("/api/health")
        database = health.json().get("database") if health.status_code == 200 else None
        report.check("Grafana health", "HTTP 200, database ok", f"HTTP {health.status_code}, database {database}", database == "ok")
        query = {"queries": [{"refId": "A", "datasource": {"uid": "warehouse"}, "rawSql": "SELECT 1 AS ok", "format": "table"}]}
        response = client.post("/api/ds/query", json=query)
        frames = response.json().get("results", {}).get("A", {}).get("frames", []) if response.status_code == 200 else []
        values = frames[0]["data"]["values"] if frames else []
    report.check("Grafana queries the warehouse", "provisioned data source returns 1", f"HTTP {response.status_code}, values {values}", values == [[1]])


def is_uuid(value: object) -> bool:
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except ValueError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--env-file", type=Path, default=STACK_ENV_FILE, help="local stack settings written by local_stack.sh start")
    args = parser.parse_args(argv)
    report = Report(scenario="local_stack", purpose=PURPOSE, limits=LIMITS, reproduce=REPRODUCE)
    error: BaseException | None = None
    try:
        env = load_environment_file(args.env_file) if args.env_file.exists() else {}
        hapi_url = f"http://127.0.0.1:{setting(env, 'LOCAL_HAPI_PORT', '8080')}/fhir"
        grafana_url = f"http://127.0.0.1:{setting(env, 'LOCAL_GRAFANA_PORT', '3000')}"
        grafana_password = setting(env, "LOCAL_GRAFANA_ADMIN_PASSWORD")
        report.parameters = {"compose_file": str(COMPOSE_FILE.relative_to(ROOT))}
        check_ports(report)
        check_memory_limits(report)
        check_postgres(report)
        check_hapi(report, hapi_url)
        check_grafana(report, grafana_url, grafana_password)
    except Exception as failure:
        error = failure
    report.finish(error)
    folder = report.write()
    sys.stdout.write(f"local_stack: {report.status} ({folder.relative_to(ROOT)}/report.md)\n")
    return 0 if report.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
