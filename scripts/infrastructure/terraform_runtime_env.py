import argparse
import json
import shlex
from pathlib import Path

import hcl2

VARIABLES = {
    "AWS_REGION": "aws_region",
    "PROJECT_NAME": "project_name",
    "RAW_PREFIX": "raw_prefix",
    "AIRFLOW_PIPELINE_SCHEDULE": "airflow_pipeline_schedule",
    "ATHENA_SOURCE_DATABASE": "source_database_name",
    "ATHENA_PROCESSED_TABLE": "processed_observations_table_name",
    "ATHENA_WORKGROUP": "athena_workgroup_name",
    "ATHENA_RESULTS_S3_URI": "athena_results_s3_uri",
}


def normalize(value: object) -> str:
    if isinstance(value, str):
        try:
            return str(json.loads(value))
        except json.JSONDecodeError:
            return value
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("terraform_var_file", type=Path)
    arguments = parser.parse_args()

    with arguments.terraform_var_file.open(encoding="utf-8") as stream:
        if arguments.terraform_var_file.suffix == ".json":
            values = json.load(stream)
        else:
            values = hcl2.load(stream)

    missing = sorted(variable for variable in VARIABLES.values() if variable not in values)
    if missing:
        parser.error(f"missing Terraform variables: {', '.join(missing)}")

    for environment_name, variable_name in VARIABLES.items():
        print(f"export {environment_name}={shlex.quote(normalize(values[variable_name]))}")


if __name__ == "__main__":
    main()
