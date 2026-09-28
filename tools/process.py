"""The one place repository tooling starts another program.

Every call resolves the program to its full path, passes a list of arguments (never a shell string), closes stdin and
applies a timeout. Repository checks import from here instead of ``subprocess``, so the lint exception for starting a
process exists on one line. See docs/quality-checks.md.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired

__all__ = ["CompletedProcess", "TimeoutExpired", "clear_git_environment", "find_program", "run_command"]

DEFAULT_TIMEOUT_SECONDS = 300


def clear_git_environment() -> None:
    """Detach a test runner from its invoking hook before it operates on scratch Git repositories.

    Only test entry points call this; production checks keep their inherited staged-index context. The change applies
    to this process and its children, never the parent process or machine configuration.
    """
    variables = run_command("git", ["rev-parse", "--local-env-vars"], check=True).stdout.splitlines()
    variables.extend(f"GIT_{role}_{field}" for role in ("AUTHOR", "COMMITTER") for field in ("NAME", "EMAIL", "DATE"))
    variables.extend(("PRE_COMMIT_FROM_REF", "PRE_COMMIT_TO_REF"))
    for variable in variables:
        os.environ.pop(variable, None)


def find_program(program: str) -> str | None:
    """Return the full path of ``program``, or None when it is not installed."""
    if os.sep in program:
        return program if Path(program).exists() else None
    return shutil.which(program)


def run_command(
    program: str, args: Sequence[str], cwd: Path | None = None, timeout: float = DEFAULT_TIMEOUT_SECONDS, check: bool = False
) -> CompletedProcess[str]:
    """Run ``program`` with ``args`` and return its exit code and captured text output.

    Parameters
    ----------
    program : str
        Program name resolved on PATH, or a path to an executable.
    args : Sequence[str]
        Arguments passed as a list; no shell is involved.
    cwd : Path, optional
        Working directory for the program.
    timeout : float
        Seconds before the program is stopped.
    check : bool
        Raise when the program exits non-zero.

    Returns
    -------
    CompletedProcess[str]
        Exit code, stdout and stderr.

    Raises
    ------
    FileNotFoundError
        ``program`` cannot be found.
    subprocess.CalledProcessError
        ``check`` is true and the program exits non-zero.
    TimeoutExpired
        The program ran longer than ``timeout`` seconds.
    """
    executable = find_program(program)
    if executable is None:
        raise FileNotFoundError(f"{program} is not installed")
    return subprocess.run(  # noqa: S603 - the only process launcher: full path, list arguments, no shell, stdin closed, timeout
        [executable, *args], cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout, check=check
    )
