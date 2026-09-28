"""Commit-message policy: Conventional Commit subjects and no AI attribution.

Usage: python -m scripts.check_commit_message <message-file>   (commit-msg hook)
       python -m scripts.check_commit_message --range <a..b>   (CI; checks stored messages)

Human co-authors and factual mentions of tools stay allowed. Findings name the line, never echo the message.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from tools.process import run_command

TYPES = ("feat", "fix", "docs", "chore", "refactor", "test", "build", "ci", "perf", "style", "revert")
SUBJECT = re.compile(rf"(?:{'|'.join(TYPES)})(?:\([a-z0-9._/-]+\))?!?: \S.*")
AGENTS = ("claude", "codex", "grok", "antigravity", "chatgpt", "copilot", "gemini", "cursor", "devin", "aider", "windsurf")
AI_NAMES = re.compile(rf"\b(?:{'|'.join((*AGENTS, 'anthropic', 'openai', 'xai'))})\b", re.IGNORECASE)
CREDIT = re.compile(r"^\s*(?:co-authored-by|co-developed-by|assisted-by|generated-by)\s*:\s*(.*)$", re.IGNORECASE)
GENERATED = re.compile(r"^\s*(?:[🤖✨]\s*)?(?:generated (?:with|by)|written by)\b(.*)$", re.IGNORECASE)
SESSION = re.compile(rf"^\s*(?:{'|'.join(AGENTS)})-session\s*:", re.IGNORECASE)
SCISSORS = " ------------------------ >8 ------------------------"


def git(*args: str) -> str:
    """Run Git and return its output."""
    return run_command("git", args, check=True).stdout


def comment_prefixes() -> list[str]:
    """Return the comment prefixes Git uses for this repository."""
    comment = run_command("git", ["config", "--get", "core.commentString"])
    if comment.returncode == 1:
        comment = run_command("git", ["config", "--get", "core.commentChar"])
    if comment.returncode not in (0, 1):
        raise RuntimeError("cannot read Git's comment configuration")
    prefix = comment.stdout.strip() or "#"
    return list("#;@!$%^&|:") if prefix == "auto" else [prefix]


def without_verbose_patch(message: str) -> str:
    """Drop the patch Git appends below the scissors line of a verbose commit; keep everything else."""
    if os.environ.get("GIT_EDITOR") == ":":
        return message
    for prefix in comment_prefixes():
        before, separator, after = message.partition(f"\n{prefix}{SCISSORS}\n")
        if separator and any(line.startswith("diff --git ") for line in after.splitlines()):
            return before
    return message


def findings(where: str, message: str, *, comments: bool) -> list[str]:
    """Return one problem per non-conventional subject or AI attribution line."""
    lines = message.splitlines()
    subject = next((line for line in lines if line.strip() and not (comments and line.startswith("#"))), "")
    problems = []
    if not SUBJECT.fullmatch(subject):
        problems.append(f"{where}: subject is not a Conventional Commit (<type>(<scope>): <description>)")
    for number, line in enumerate(lines, 1):
        credit = CREDIT.match(line) or GENERATED.match(line)
        if SESSION.match(line) or (credit and AI_NAMES.search(credit.group(1))):
            problems.append(f"{where}:{number}: AI attribution; remove the AI credit or session line (human co-authors are fine)")
    return problems


def main(argv: list[str] | None = None) -> int:
    """Check one message file or every stored message in a revision range."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("message_file", nargs="?", type=Path)
    parser.add_argument("--range", dest="revision_range")
    args = parser.parse_args(argv)
    if args.revision_range:
        revisions = git("rev-list", "--reverse", args.revision_range).split()
        problems = [p for rev in revisions for p in findings(rev[:7], git("log", "-1", "--format=%B", rev), comments=False)]
    elif args.message_file:
        problems = findings("commit message", without_verbose_patch(args.message_file.read_text(encoding="utf-8")), comments=True)
    else:
        parser.error("give a message file or --range <a..b>")
    for problem in problems:
        sys.stderr.write(f"{problem}\n")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
