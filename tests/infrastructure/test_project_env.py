from __future__ import annotations

from pathlib import Path

from testkit import expect
from tools.process import CompletedProcess, run_command

REPO_ROOT = Path(__file__).resolve().parents[2]
LOADER = REPO_ROOT / "scripts/infrastructure/project_env.sh"


def run_loader(env_file: Path, command: str) -> CompletedProcess[str]:
    return run_command("bash", ["-c", f'source "{LOADER}"; load_project_env "{env_file}" || exit $?; {command}'])


def test_loads_assignments_without_executing_shell(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("REGION=example-region-1\nQUOTED='project value'\n", encoding="utf-8")

    result = run_loader(env_file, 'printf \'%s|%s\' "$REGION" "$QUOTED"')

    expect.equal(result.returncode, 0)
    expect.equal(result.stdout, "example-region-1|project value")


def test_environment_file_has_precedence(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("REGION=file-region\n", encoding="utf-8")

    result = run_loader(env_file, "printf '%s' \"$REGION\"")
    result_with_override = run_command("bash", ["-c", f'export REGION=shell-region; source "{LOADER}"; load_project_env "{env_file}"; printf "%s" "$REGION"'])

    expect.equal(result.stdout, "file-region")
    expect.equal(result_with_override.stdout, "file-region")


def test_rejects_non_assignment_lines(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("echo unsafe\n", encoding="utf-8")

    result = run_loader(env_file, ":")

    expect.equal(result.returncode, 2)
    expect.is_in("Invalid environment assignment", result.stderr)


def test_each_environment_gets_its_own_local_state_workspace(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("DEPLOYMENT_ENVIRONMENT=staging\n", encoding="utf-8")
    development = tmp_path / "development.env"
    development.write_text("AWS_REGION=example-region-1\n", encoding="utf-8")

    expect.equal(run_loader(env_file, "environment_workspace").stdout.strip(), "staging")
    expect.equal(run_loader(development, "unset DEPLOYMENT_ENVIRONMENT; environment_workspace").stdout.strip(), "default")
