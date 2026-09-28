"""Commit-message policy: Conventional Commit subjects and no AI attribution.

Usage: python scripts/check_commit_message.py <message-file>   (commit-msg hook)
       python scripts/check_commit_message.py --range <a..b>   (CI; checks stored messages)

Human co-authors and factual mentions of tools stay allowed. Findings name the line, never echo the message.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

TYPES = ("feat", "fix", "docs", "chore", "refactor", "test", "build", "ci", "perf", "style", "revert")
SUBJECT = re.compile(rf"(?:{'|'.join(TYPES)})(?:\([a-z0-9._/-]+\))?!?: \S.*")
AGENTS = ("claude", "codex", "grok", "antigravity", "chatgpt", "copilot", "gemini", "cursor", "devin", "aider", "windsurf")
AI_NAMES = re.compile(rf"\b(?:{'|'.join((*AGENTS, 'anthropic', 'openai', 'xai'))})\b", re.IGNORECASE)
CREDIT = re.compile(r"^\s*(?:co-authored-by|co-developed-by|assisted-by|generated-by)\s*:\s*(.*)$", re.IGNORECASE)
GENERATED = re.compile(r"^\s*(?:[🤖✨]\s*)?(?:generated (?:with|by)|written by)\b(.*)$", re.IGNORECASE)
SESSION = re.compile(rf"^\s*(?:{'|'.join(AGENTS)})-session\s*:", re.IGNORECASE)
SCISSORS = re.compile(r"^# -+ >8 -+$")


def strip_comments(message: str) -> list[str]:
    """Drop Git comment lines and everything below the verbose-commit scissors line."""
    lines: list[str] = []
    for line in message.splitlines():
        if SCISSORS.match(line):
            break
        if not line.startswith("#"):
            lines.append(line)
    return lines


def findings(where: str, message: str, *, comments: bool) -> list[str]:
    """Return one problem per non-conventional subject or AI attribution line."""
    lines = strip_comments(message) if comments else message.splitlines()
    problems = []
    subject = next((line for line in lines if line.strip()), "")
    if not SUBJECT.fullmatch(subject):
        problems.append(f"{where}: subject is not a Conventional Commit (<type>(<scope>): <description>)")
    for number, line in enumerate(lines, 1):
        credit = CREDIT.match(line) or GENERATED.match(line)
        if SESSION.match(line) or (credit and AI_NAMES.search(credit.group(1))):
            problems.append(f"{where}:{number}: AI attribution; remove the AI credit or session line (human co-authors are fine)")
    return problems


def git(*args: str) -> str:
    """Run Git and return its output."""
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("message_file", nargs="?", type=Path)
    parser.add_argument("--range", dest="revision_range")
    args = parser.parse_args(argv)
    if args.revision_range:
        revisions = git("rev-list", "--reverse", args.revision_range).split()
        problems = [p for rev in revisions for p in findings(rev[:7], git("log", "-1", "--format=%B", rev), comments=False)]
    elif args.message_file:
        problems = findings("commit message", args.message_file.read_text(encoding="utf-8"), comments=True)
    else:
        parser.error("give a message file or --range <a..b>")
    for problem in problems:
        sys.stderr.write(f"{problem}\n")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
