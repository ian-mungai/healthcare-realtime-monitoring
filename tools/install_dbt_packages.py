"""Install the dbt packages pinned in dbt/package-lock.yml without a deployment.

dbt imports every top-level module whose name starts with ``dbt_`` as a plugin, so this file must not use that prefix.

Usage: python -m tools.install_dbt_packages <dbt executable> <project dir>

``dbt deps`` parses dbt_project.yml, which reads deployment names through ``env_var``. This runner supplies the same
fixed placeholders as tools/lint_sql.py, so it works in a Docker build, in CI and on a clean clone with no ``.env``. It
makes no AWS call. Idempotent: dbt installs the locked versions again and reports them up to date.
"""

from __future__ import annotations

import os
import sys

from tools.lint_sql import AWS_LOGIN_VARIABLES, PLACEHOLDERS
from tools.process import run_command


def main(argv: list[str] | None = None) -> int:
    """Run dbt deps for the project with placeholder deployment names."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        sys.stderr.write("usage: python -m tools.install_dbt_packages <dbt executable> <project dir>\n")
        return 2
    dbt, project_dir = args
    environment = {name: value for name, value in os.environ.items() if name not in AWS_LOGIN_VARIABLES} | PLACEHOLDERS
    result = run_command(dbt, ["deps", "--project-dir", project_dir], timeout=600, env=environment, capture=False)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
