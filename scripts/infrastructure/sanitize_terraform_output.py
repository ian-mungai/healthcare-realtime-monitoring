#!/usr/bin/env python3

import argparse
import json
import re
from pathlib import Path

REDACTIONS = (
    (re.compile(r"arn:aws(?:-[a-z]+)?:[^\s\"']+"), "<aws-arn>"),
    (re.compile(r"(?<!\d)\d{12}(?!\d)"), "<aws-account-id>"),
    (re.compile(r"[A-Za-z0-9-]+\.execute-api\.[A-Za-z0-9-]+\.amazonaws\.com"), "<api-gateway-endpoint>"),
    (re.compile(r"[A-Za-z0-9.-]+\.elb\.amazonaws\.com"), "<load-balancer-endpoint>"),
    (re.compile(r"s3://[A-Za-z0-9._-]+"), "s3://<bucket>"),
)


def collect_string_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for nested in value.values() for item in collect_string_values(nested)]
    if isinstance(value, list):
        return [item for nested in value for item in collect_string_values(nested)]
    return []


def sanitize(output: str, explicit_values: list[str]) -> str:
    sanitized = output
    for value in sorted((value for value in explicit_values if value), key=len, reverse=True):
        sanitized = sanitized.replace(value, "<redacted>")
    for pattern, replacement in REDACTIONS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


def main() -> None:
    parser = argparse.ArgumentParser(description="Redact deployment identifiers from Terraform diagnostics.")
    parser.add_argument("log_file", type=Path)
    parser.add_argument("--redact", action="append", default=[])
    parser.add_argument("--values-json", type=Path)
    args = parser.parse_args()
    explicit_values = args.redact
    if args.values_json:
        values = json.loads(args.values_json.read_text(encoding="utf-8"))
        explicit_values.extend(collect_string_values(values))
    print(sanitize(args.log_file.read_text(encoding="utf-8", errors="replace"), explicit_values), end="")


if __name__ == "__main__":
    main()
