import argparse
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("policy")
    parser.add_argument("--output", required=True)

    arguments = parser.parse_args()

    source_path = Path(arguments.policy)
    output_path = Path(arguments.output)

    replacements = {
        "${AWS_ACCOUNT_ID}": os.environ["AWS_ACCOUNT_ID"],
        "${DATA_BUCKET_NAME}": os.environ.get("DATA_BUCKET_NAME", "healthcare-realtime-data"),
        "${MWAA_BUCKET_NAME}": os.environ.get("MWAA_BUCKET_NAME", "healthcare-realtime-mwaa"),
        "${EMAIL_ADDRESS}": os.environ.get("EMAIL_ADDRESS", "alerts@example.com"),
    }

    content = source_path.read_text(encoding="utf-8")

    for placeholder, replacement in replacements.items():
        content = content.replace(placeholder, replacement)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
