#!/usr/bin/env python3

import argparse
import json
import re
from pathlib import Path


def describe_actions(actions: list[str]) -> str:
    action_set = set(actions)
    if action_set == {"create"}:
        return "create"
    if action_set == {"update"}:
        return "update"
    if action_set == {"delete"}:
        return "destroy"
    if action_set == {"create", "delete"}:
        return "replace"
    if action_set == {"read"}:
        return "read"
    return " + ".join(actions)


def sanitize_address(address: str) -> str:
    return re.sub(r'\["(?:[^"\\]|\\.)*"\]', '["<key>"]', address)


def summarize(plan: dict) -> str:
    changes: list[tuple[str, str]] = []
    for resource in plan.get("resource_changes", []):
        actions = resource.get("change", {}).get("actions", [])
        if actions == ["no-op"]:
            continue
        changes.append((describe_actions(actions), sanitize_address(resource["address"])))

    lines = ["## Terraform plan review", ""]
    if not changes:
        lines.append("No resource changes.")
        return "\n".join(lines)

    counts: dict[str, int] = {}
    for action, _ in changes:
        counts[action] = counts.get(action, 0) + 1
    count_text = ", ".join(f"{count} {action}" for action, count in sorted(counts.items()))
    lines.extend([f"**Summary:** {count_text}.", "", "| Action | Resource |", "|---|---|"])
    for action, address in changes:
        lines.append(f"| `{action}` | `{address}` |")

    if any(action in {"destroy", "replace"} for action, _ in changes):
        lines.extend(["", "**Review required:** this plan destroys or replaces resources."])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a value-free Terraform plan summary.")
    parser.add_argument("plan_json", type=Path)
    args = parser.parse_args()
    plan = json.loads(args.plan_json.read_text(encoding="utf-8"))
    print(summarize(plan))


if __name__ == "__main__":
    main()
