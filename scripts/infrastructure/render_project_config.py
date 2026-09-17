from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = REPO_ROOT / ".env"
DEFAULT_DEFAULTS_FILE = REPO_ROOT / "config" / "deployment.defaults.json"
DEFAULT_DEPLOYMENT_OUTPUT = REPO_ROOT / "infra" / "deployment.auto.tfvars.json"
DEFAULT_BOOTSTRAP_OUTPUT = REPO_ROOT / "infra" / "bootstrap" / "deployment.auto.tfvars.json"

STRING_VARIABLES = {
    "AWS_REGION": "aws_region",
    "PROJECT_NAME": "project_name",
    "DATA_BUCKET_NAME": "data_bucket_name",
    "MWAA_SOURCE_BUCKET_NAME": "mwaa_source_bucket_name",
    "REALTIME_ALERT_EMAIL": "realtime_alert_email",
    "FHIR_WEBHOOK_SECRET_ID": "fhir_webhook_secret_id",
    "OPENLINEAGE_COLLECTOR_URL": "openlineage_collector_url",
    "GITHUB_REPOSITORY": "github_repository",
    "GITHUB_OIDC_SUBJECT_PREFIX": "github_oidc_subject_prefix",
    "GITHUB_DEPLOYMENT_ENVIRONMENT": "github_deployment_environment",
    "ML_APPROVED_MODEL_VERSION": "ml_approved_model_version",
}

GENERATED_STRING_VARIABLES = {
    "VITALS_SIMULATOR_IMAGE_TAG": "vitals_simulator_image_tag",
    "DBT_IMAGE_TAG": "dbt_image_tag",
    "SODA_IMAGE_TAG": "soda_image_tag",
    "OPENLINEAGE_COLLECTOR_IMAGE_TAG": "openlineage_collector_image_tag",
}

BOOLEAN_VARIABLES = {"ENABLE_OPENLINEAGE_COLLECTOR": "enable_openlineage_collector", "ENABLE_GITHUB_OIDC": "enable_github_oidc"}

INTEGER_VARIABLES = {"OPENLINEAGE_COLLECTOR_DESIRED_COUNT": "openlineage_collector_desired_count"}

REQUIRED_ENVIRONMENT = {
    "AWS_ACCOUNT_ID",
    "AWS_REGION",
    "DATA_BUCKET_NAME",
    "ENABLE_GITHUB_OIDC",
    "ENABLE_OPENLINEAGE_COLLECTOR",
    "FHIR_WEBHOOK_SECRET_ID",
    "GITHUB_DEPLOYMENT_ENVIRONMENT",
    "GITHUB_OIDC_SUBJECT_PREFIX",
    "GITHUB_REPOSITORY",
    "ML_APPROVED_MODEL_VERSION",
    "MWAA_SOURCE_BUCKET_NAME",
    "OPENLINEAGE_COLLECTOR_DESIRED_COUNT",
    "OPENLINEAGE_COLLECTOR_URL",
    "PATIENT_IDS",
    "PROJECT_NAME",
    "REALTIME_ALERT_EMAIL",
    "REALTIME_PATIENT_ACCESS_PRINCIPALS",
    "TF_STATE_BUCKET",
}


class ConfigurationError(ValueError):
    pass


def load_environment_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        raise ConfigurationError(f"environment file not found: {path}")
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ConfigurationError(f"invalid environment assignment at {path}:{line_number}")
        name, value = line.split("=", 1)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ConfigurationError(f"invalid environment name at {path}:{line_number}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[name] = value
    return values


def require_value(environment: dict[str, str], name: str) -> str:
    value = environment.get(name, "").strip()
    if not value or "<" in value or ">" in value:
        raise ConfigurationError(f"set {name} in .env")
    return value


def parse_boolean(value: str, name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise ConfigurationError(f"{name} must be true or false")


def parse_csv(value: str, name: str) -> list[str]:
    values = [item.strip() for item in value.split(",") if item.strip()]
    if not values:
        raise ConfigurationError(f"{name} must contain at least one value")
    if len(values) != len(set(values)):
        raise ConfigurationError(f"{name} must not contain duplicates")
    return values


def load_defaults(path: Path) -> dict[str, Any]:
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigurationError(f"unable to load deployment defaults: {error}") from error
    if not isinstance(values.get("terraform"), dict) or not isinstance(values.get("github_deployment_policy_names"), list):
        raise ConfigurationError("deployment defaults must contain terraform and github_deployment_policy_names")
    return values


def build_configuration(environment: dict[str, str], defaults: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    effective = environment
    for name in sorted(REQUIRED_ENVIRONMENT):
        if name == "ML_APPROVED_MODEL_VERSION" or name == "OPENLINEAGE_COLLECTOR_URL":
            if name not in effective:
                raise ConfigurationError(f"set {name} in .env; an empty value is allowed")
            continue
        require_value(effective, name)

    account_id = require_value(effective, "AWS_ACCOUNT_ID")
    if not re.fullmatch(r"[0-9]{12}", account_id):
        raise ConfigurationError("AWS_ACCOUNT_ID must contain 12 digits")

    patient_ids = parse_csv(require_value(effective, "PATIENT_IDS"), "PATIENT_IDS")
    if len(patient_ids) != 10:
        raise ConfigurationError("PATIENT_IDS must contain exactly ten patient identifiers")
    principals = parse_csv(require_value(effective, "REALTIME_PATIENT_ACCESS_PRINCIPALS"), "REALTIME_PATIENT_ACCESS_PRINCIPALS")

    deployment = dict(defaults["terraform"])
    for environment_name, terraform_name in STRING_VARIABLES.items():
        deployment[terraform_name] = effective.get(environment_name, "").strip()
    for environment_name, terraform_name in GENERATED_STRING_VARIABLES.items():
        if value := effective.get(environment_name, "").strip():
            deployment[terraform_name] = value
    for environment_name, terraform_name in BOOLEAN_VARIABLES.items():
        deployment[terraform_name] = parse_boolean(require_value(effective, environment_name), environment_name)
    for environment_name, terraform_name in INTEGER_VARIABLES.items():
        raw_value = require_value(effective, environment_name)
        try:
            deployment[terraform_name] = int(raw_value)
        except ValueError as error:
            raise ConfigurationError(f"{environment_name} must be an integer") from error

    data_bucket = require_value(effective, "DATA_BUCKET_NAME")
    results_prefix = str(deployment.pop("athena_results_prefix")).strip("/")
    deployment["athena_results_s3_uri"] = f"s3://{data_bucket}/{results_prefix}/"
    deployment["active_patient_ids"] = patient_ids
    deployment["realtime_patient_access_policy"] = {principal: patient_ids for principal in principals}
    deployment["github_deployment_policy_arns"] = [f"arn:aws:iam::{account_id}:policy/{name}" for name in defaults["github_deployment_policy_names"]]

    project_name = require_value(effective, "PROJECT_NAME")
    state_region = effective.get("TF_STATE_REGION", "").strip() or require_value(effective, "AWS_REGION")
    bootstrap = {"aws_region": state_region, "project_name": project_name, "state_bucket_name": require_value(effective, "TF_STATE_BUCKET")}
    return deployment, bootstrap


def rendered_json(values: dict[str, Any]) -> str:
    return json.dumps(values, indent=2, sort_keys=True) + "\n"


def write_or_check(path: Path, content: str, check: bool) -> None:
    if check:
        if not path.is_file() or path.read_text(encoding="utf-8") != content:
            raise ConfigurationError(f"generated configuration is stale: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render ignored Terraform inputs from the project environment.")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--defaults-file", type=Path, default=DEFAULT_DEFAULTS_FILE)
    parser.add_argument("--deployment-output", type=Path, default=DEFAULT_DEPLOYMENT_OUTPUT)
    parser.add_argument("--bootstrap-output", type=Path, default=DEFAULT_BOOTSTRAP_OUTPUT)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()

    try:
        environment = load_environment_file(arguments.env_file)
        deployment, bootstrap = build_configuration(environment, load_defaults(arguments.defaults_file))
        write_or_check(arguments.deployment_output, rendered_json(deployment), arguments.check)
        write_or_check(arguments.bootstrap_output, rendered_json(bootstrap), arguments.check)
    except ConfigurationError as error:
        parser.error(str(error))

    action = "Verified" if arguments.check else "Rendered"
    print(f"{action} ignored Terraform configuration from .env.")


if __name__ == "__main__":
    main()
