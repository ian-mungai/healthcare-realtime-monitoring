"""Check Markdown prose and metadata without editing documents.

Run through pre-commit or ``python -m tools.documentation_checks writing-check|front-matter``.
Findings name locations and remedies; warning mode is for migration preparation only.
"""

from __future__ import annotations

import argparse
import datetime
import fnmatch
import importlib
import os
import re
import sys
from pathlib import Path

from tools.repo_checks import Finding, git

DATA_FOLDERS = ("artifacts/e2e/",)
WRITING_RULE = "repository-policy#writing-preferences"
WRITING_ALLOWLIST = ".writing_allowlist"
# Checked in prose only: code spans, fenced blocks, front matter, URLs and link targets are masked first.
WRITING_PATTERNS = {
    "comma-and": ("comma before a final 'and', 'or' or 'nor'", re.compile(r",\s+(?:and|or|nor)\b"), "drop the comma, or split the sentence in two"),
    "iso-date": ("ISO date in prose", re.compile(r"\b\d{4}-\d{2}-\d{2}\b"), "write the date as Sep 30 2026, or put a machine value in `code`"),
    # Only the always time-bound words; "now", "new", "latest", "yet" and "old" have timeless procedural uses and are judged in review.
    "time-word": (
        "time-bound word in prose",
        re.compile(r"(?i)\b(?:currently|recently|eventually|(?<!as )soon(?! as)|as of this writing|at present|in the future|for now)\b"),
        "state the fact without the time word, or tie it to a version, commit or issue",
    ),
    "em-dash": ("em dash in article text", re.compile("\u2014"), "use a colon, comma, parentheses or a new sentence"),
}
ARTICLE_ONLY = {"em-dash"}


def read_allowlist(name: str, kinds: list[str], rule: str, reason: str) -> tuple[list[tuple[str, str]], list[Finding]]:
    """Read ``type glob -- reason`` entries; an entry without a reason or with an unknown type is itself a finding."""
    entries: list[tuple[str, str]] = []
    findings: list[Finding] = []
    if not Path(name).exists():
        return entries, findings
    for number, line in enumerate(Path(name).read_text().splitlines(), 1):
        text = "" if line.lstrip().startswith("#") else line.strip()
        if not text:
            continue
        match = re.fullmatch(r"(\S+)\s+(\S+)(?:\s+--\s*(.*))?", text)
        location = f"{name}:{number}"
        if not match or match.group(1) not in kinds:
            findings.append(Finding(location, "allowlist entry with an unknown type", rule, f"use one of: {', '.join(kinds)}"))
        elif not (match.group(3) or "").strip():
            findings.append(Finding(location, "allowlist entry without a reason", rule, f"add ' -- <{reason}>'"))
        else:
            entries.append((match.group(1), match.group(2)))
    return entries, findings


def mask_prose(line: str) -> str:
    """Replace code spans, link targets and URLs with a neutral word, so only prose is checked.

    A neutral word, not blanks: blanking would turn "`a`, `b` and `c`" into a comma followed by spaces and "and".
    """
    line = re.sub(r"`[^`\n]*`", "code", line)
    line = re.sub(r"\]\([^)\s]*\)", "]", line)
    return re.sub(r"https?://\S+", "url", line)


def prose_lines(text: str) -> list[tuple[int, str]]:
    """Mask prose outside YAML metadata and correctly matched Markdown fences."""
    lines: list[tuple[int, str]] = []
    fence = ""
    front = False
    for number, line in enumerate(text.splitlines(), 1):
        if number == 1 and line.strip() == "---":
            front = True
            continue
        if front:
            front = line.strip() != "---"
            continue
        stripped = line.lstrip()
        marker = re.match(r"(`{3,}|~{3,})(.*)$", stripped)
        if fence:
            if marker and marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence) and not marker.group(2).strip():
                fence = ""
            continue
        if marker:
            fence = marker.group(1)
            continue
        lines.append((number, mask_prose(line)))
    return lines


def writing_check(articles: list[str]) -> list[Finding]:
    """Rule 1.2: prose in Markdown follows the writing preferences; em dashes are checked in declared article files only.

    E2E artifact folders (``DATA_FOLDERS``) are recorded evidence and are not rewritten, so they are skipped.
    """
    allowed, findings = read_allowlist(WRITING_ALLOWLIST, list(WRITING_PATTERNS), WRITING_RULE, "why this text is kept as is")
    for path in sorted(set(git("ls-files", "--cached", "--others", "--exclude-standard").splitlines())):
        article = any(fnmatch.fnmatch(path, glob) for glob in articles)
        if not (path.endswith(".md") or article) or path.startswith(DATA_FOLDERS) or not os.path.isfile(path):
            continue
        for number, line in prose_lines(Path(path).read_text(errors="replace")):
            for kind, (description, pattern, fix) in WRITING_PATTERNS.items():
                if kind in ARTICLE_ONLY and not article:
                    continue
                if pattern.search(line) and not any(kind == entry_kind and fnmatch.fnmatch(path, glob) for entry_kind, glob in allowed):
                    findings.append(Finding(f"{path}:{number}", description, WRITING_RULE, fix))
    return findings


FRONT_RULE = "repository-policy#document-metadata"
# Well-known files (documentation conventions) need no front matter; READMEs and E2E records are out of scope.
WELL_KNOWN = {"AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md", "CHANGELOG.md", "SECURITY.md", "CODE_OF_CONDUCT.md", "SUPPORT.md", "LICENSE.md"}
DESCRIPTION_LIMIT = 120
ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def load_yaml(text: str) -> object:
    """Parse YAML with PyYAML's safe loader; PyYAML ships no type hints, so it is imported by name."""
    yaml = importlib.import_module("yaml")
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ValueError(str(error).splitlines()[0]) from error


def exempt_from_front_matter(path: str, loaded: set[str]) -> bool:
    """Return whether a Markdown file needs no front matter: README, well-known, .github template or tool-conventional."""
    name = os.path.basename(path)
    return name in WELL_KNOWN or re.fullmatch(r"README(?:\.[A-Za-z0-9-]+)?\.md", name) is not None or path.startswith(".github/") or path in loaded


def first_h1(text: str) -> str | None:
    """The first level-one heading outside fenced code blocks."""
    fenced = False
    for line in text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        elif not fenced and line.startswith("# "):
            return line[2:].strip()
    return None


def front_matter_problems(path: str, text: str) -> list[str]:
    """Problems with one document's front matter under the document metadata policy (SKILL.md keeps title and date under metadata)."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return ["no front matter: start the file with --- title, description and last_updated ---"]
    if "---" not in (line.strip() for line in lines[1:]):
        return ["front matter is not closed with a --- line"]
    end = next(number for number, line in enumerate(lines[1:], 1) if line.strip() == "---")
    try:
        data = load_yaml("\n".join(lines[1:end]))
    except ValueError as error:
        return [f"front matter is not valid YAML ({error}); quote values that contain ': '"]
    if not isinstance(data, dict):
        return ["front matter is not valid YAML: expected key: value lines"]
    skill = os.path.basename(path) == "SKILL.md"
    fields = data.get("metadata") if skill else data
    fields = fields if isinstance(fields, dict) else {}
    problems = []
    title, description, updated = fields.get("title"), data.get("description"), fields.get("last_updated")
    if not isinstance(title, str) or title != first_h1(text):
        problems.append("title does not match the H1")
    if not isinstance(description, str) or not description.strip():
        problems.append("description is missing")
    elif not skill and len(description) > DESCRIPTION_LIMIT:
        problems.append(f"description over {DESCRIPTION_LIMIT} characters ({len(description)})")
    if not (type(updated) is datetime.date or (isinstance(updated, str) and valid_date(updated))):
        problems.append("last_updated is not a YYYY-MM-DD date")
    return problems


def front_matter() -> list[Finding]:
    """Every in-scope Markdown document has valid front matter with the document metadata policy fields."""
    loaded: set[str] = set()
    findings = []
    for path in sorted(git("ls-files", "--cached", "--others", "--exclude-standard").splitlines()):
        if not path.endswith(".md") or path.startswith(DATA_FOLDERS) or exempt_from_front_matter(path, loaded) or not os.path.isfile(path):
            continue
        for problem in front_matter_problems(path, Path(path).read_text(errors="replace")):
            findings.append(Finding(f"{path}:1", problem, FRONT_RULE, "fix the front matter; SKILL.md keeps title and last_updated under metadata"))
    return findings


def valid_date(value: str) -> bool:
    """Accept a real calendar date in ISO format."""
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return False
    return ISO_DAY.fullmatch(value) is not None


def main() -> int:
    """Report every finding and fail unless explicit migration warning mode is selected."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("check", choices=["writing-check", "front-matter"])
    parser.add_argument("--warn", action="store_true")
    args = parser.parse_args()
    findings = writing_check(["docs/building-*.md"]) if args.check == "writing-check" else front_matter()
    for finding in findings:
        prefix = "warning: " if args.warn else ""
        sys.stdout.write(f"{prefix}{finding.location}: {finding.problem}\n  rule: {finding.rule}\n  fix: {finding.fix}\n")
    return int(bool(findings) and not args.warn)


if __name__ == "__main__":
    sys.exit(main())
