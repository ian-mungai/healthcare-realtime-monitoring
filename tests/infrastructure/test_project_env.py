from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LOADER = REPO_ROOT / "scripts/infrastructure/project_env.sh"


def run_loader(env_file: Path, command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", f'source "{LOADER}"; load_project_env "{env_file}" || exit $?; {command}'], check=False, capture_output=True, text=True
    )


def test_loads_assignments_without_executing_shell(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("REGION=example-region-1\nQUOTED='project value'\n", encoding="utf-8")

    result = run_loader(env_file, 'printf \'%s|%s\' "$REGION" "$QUOTED"')

    assert result.returncode == 0
    assert result.stdout == "example-region-1|project value"


def test_environment_file_has_precedence(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("REGION=file-region\n", encoding="utf-8")

    result = run_loader(env_file, "printf '%s' \"$REGION\"")
    result_with_override = subprocess.run(
        ["bash", "-c", f'export REGION=shell-region; source "{LOADER}"; load_project_env "{env_file}"; printf "%s" "$REGION"'],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.stdout == "file-region"
    assert result_with_override.stdout == "file-region"


def test_rejects_non_assignment_lines(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("echo unsafe\n", encoding="utf-8")

    result = run_loader(env_file, ":")

    assert result.returncode == 2
    assert "Invalid environment assignment" in result.stderr
