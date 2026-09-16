import argparse
import json
import os
import re
from pathlib import Path

import hcl2

TERRAFORM_VARIABLES = {
    "PROJECT_NAME": "project_name",
    "AWS_REGION": "aws_region",
    "DATA_BUCKET_NAME": "data_bucket_name",
    "MWAA_BUCKET_NAME": "mwaa_source_bucket_name",
    "KINESIS_STREAM_NAME": "kinesis_stream_name",
    "LOAD_TEST_KINESIS_STREAM_NAME": "load_test_kinesis_stream_name",
    "FIREHOSE_DELIVERY_STREAM_NAME": "firehose_delivery_stream_name",
    "GLUE_JOB_NAME": "glue_job_name",
    "SOURCE_DATABASE_NAME": "source_database_name",
    "DBT_DATABASE_NAME": "dbt_database_name",
    "ML_DATABASE_NAME": "ml_database_name",
    "API_STAGE_NAME": "api_stage_name",
    "LATEST_VITALS_TABLE_NAME": "latest_vitals_table_name",
    "PROCESSED_OBSERVATIONS_STATE_TABLE_NAME": "processed_observations_state_table_name",
    "LOAD_TEST_RESULTS_TABLE_NAME": "load_test_results_table_name",
    "WEBSOCKET_CONNECTIONS_TABLE_NAME": "websocket_connections_table_name",
}


def load_terraform_variables(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    with path.open(encoding="utf-8") as stream:
        values = hcl2.load(stream)

    def normalize(value: object) -> str:
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                return value
            return str(decoded)
        return str(value)

    return {placeholder: normalize(values[variable]) for placeholder, variable in TERRAFORM_VARIABLES.items() if variable in values}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("policy")
    parser.add_argument("--output", required=True)
    parser.add_argument("--terraform-var-file", type=Path)

    arguments = parser.parse_args()

    source_path = Path(arguments.policy)
    output_path = Path(arguments.output)

    content = source_path.read_text(encoding="utf-8")
    terraform_values = load_terraform_variables(arguments.terraform_var_file)
    values = {**terraform_values, **os.environ}

    placeholders = set(re.findall(r"\$\{([A-Z0-9_]+)\}", content))
    unresolved = sorted(name for name in placeholders if not values.get(name))
    if unresolved:
        parser.error(f"missing values for: {', '.join(unresolved)}")

    for name in placeholders:
        content = content.replace(f"${{{name}}}", values[name])

    json.loads(content)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
