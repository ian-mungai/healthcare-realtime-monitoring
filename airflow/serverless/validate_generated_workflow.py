"""Check the generated MWAA Serverless workflow files against their DAGs and for leaked deployment values.

Usage: PYTHONPATH=airflow/serverless:airflow/dags:. python airflow/serverless/validate_generated_workflow.py [PATH ...]

Run it after generate_healthcare_realtime_pipeline.py with the same environment; without a path it checks every
workflow. Each file is named after its DAG and must equal the definition that DAG produces now, so the shared check
cannot drift from the DAG, and it must hold no account ID, Amazon Resource Name (ARN) or ECS task revision, so it stays
shareable. Local runs and CI both use this script; the DAGs' structure is covered by tests/test_workflow_generation.py.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import generate_healthcare_realtime_pipeline as generator
import yaml

# (problem, pattern) checked on the file text.
LEAKS = (
    ("an account ID", re.compile(r"(?<!\d)\d{12}(?!\d)")),
    ("an ARN", re.compile(r"\barn:aws")),
    ("a task revision", re.compile(r"task_definition:\s*\S+:\d+\s*$", re.MULTILINE)),
)


def problems(path: Path) -> list[str]:
    """Every problem with the generated file; an empty list when it is current and shareable."""
    content = path.read_text(encoding="utf-8")
    found = []
    if yaml.safe_load(content) != generator.build_workflow_definition(path.stem):
        found.append(f"{path} does not match the DAG's current definition; regenerate it")
    for problem, pattern in LEAKS:
        if pattern.search(content) or (problem == "a task revision" and "task-definition/" in content):
            found.append(f"{path} contains {problem}")
    return found


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    paths = [Path(argument) for argument in arguments] or [generator.output_path(name) for name in generator.WORKFLOWS]
    found = [problem for path in paths for problem in problems(path)]
    for problem in found:
        sys.stderr.write(problem + "\n")
    if not found:
        sys.stdout.write("MWAA Serverless workflow validation passed.\n")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
