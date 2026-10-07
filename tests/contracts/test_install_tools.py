"""The project-local tool installer's version probe.

Failure mode (written before the fix): a tool environment whose Python was removed, for example by a Homebrew upgrade,
leaves scripts whose interpreter no longer exists. Probing such a tool must report it as not installed, so the
installer rebuilds it, instead of crashing before any tool is reinstalled.
"""

from __future__ import annotations

from pathlib import Path

from testkit import expect
from tools.install_tools import installed_version


def test_a_tool_whose_interpreter_is_gone_counts_as_not_installed(tmp_path: Path) -> None:
    script = tmp_path / "checkov"
    script.write_text(f"#!{tmp_path / 'removed-python'}\nprint('3.3.19')\n", encoding="utf-8")
    script.chmod(0o755)

    expect.equal(installed_version(script, "--version"), "")
