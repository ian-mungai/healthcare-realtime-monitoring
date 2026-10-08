"""Compute container memory limits at launch from the memory free then; no limit is fixed.

Usage: python -m tools.memory_budget stack --output deploy/local/compose.memory.yaml [--explain]

Docker's memory is shared with the containers of every project on this machine, so each launch plans from what is free at
that moment. The budget is the smaller of (a) Docker's total less what running containers use now and (b) the memory the
host can give without swapping (free, file-backed and purgeable pages from vm_stat; MemAvailable on Linux), each less
HEADROOM. (b) is skipped when the Docker VM already holds its full allocation, because that memory is no longer the
host's to give. scripts/local/local_stack.sh start writes the stack's limits as a Compose override; the lock compiler
(tools/compile_requirements.py) gives the whole budget to its one container. A budget below a floor stops with the
figures instead of falling back to a fixed value. Failure modes: tests/contracts/test_memory_budget.py.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from tools.process import find_program, run_command

GIB = 1024**3
MIB = 1024**2
# Room for Docker's own processes and the overshoot of a service past its limit before the kernel reclaims memory.
HEADROOM = 2 * GIB
# The share of the budget each local stack service gets, and the least it can start with.
STACK_SHARES = {"postgres": 0.40, "hapi": 0.45, "grafana": 0.15}
STACK_FLOORS = {"postgres": 1 * GIB, "hapi": 3 * GIB // 2, "grafana": 256 * MIB}
# pip-compile resolving one lock.
LOCK_FLOOR = 1 * GIB
# The local stack's Compose project; its own containers are recreated with the new limits at each start.
STACK_PROJECT = "healthcare-realtime-local"
# The Docker VM counts as holding its full allocation from this fraction of Docker's total.
VM_CAP_FRACTION = 0.95
VM_PROCESS = "com.apple.Virtualization.VirtualMachine"
UNITS = {"B": 1, "KB": 1000, "KIB": 1024, "MB": 1000**2, "MIB": MIB, "GB": 1000**3, "GIB": GIB, "TB": 1000**4, "TIB": 1024**4}
SIZE = re.compile(r"\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]+)\s*")
PAGE_SIZE = re.compile(r"page size of (\d+) bytes")
PAGES = re.compile(r"^(Pages free|Pages purgeable|File-backed pages):\s+(\d+)\.", re.MULTILINE)


class BudgetError(RuntimeError):
    """Docker or the host could not be read, a size was not understood or too little memory is free."""


@dataclass(frozen=True)
class Budget:
    """The figures a budget comes from, in bytes; mac_available is None when it was skipped."""

    docker_total: int
    container_use: int
    mac_available: int | None
    limit: int

    def record(self) -> dict[str, int | None]:
        return {
            "docker_total": self.docker_total,
            "container_use": self.container_use,
            "mac_available": self.mac_available,
            "headroom": HEADROOM,
            "limit": self.limit,
        }

    def describe(self) -> str:
        mac = "skipped" if self.mac_available is None else f"{self.mac_available / GIB:.1f} GiB"
        return (
            f"budget {self.limit / GIB:.1f} GiB: Docker {self.docker_total / GIB:.1f} GiB, containers {self.container_use / GIB:.1f} GiB, "
            f"host available {mac}, headroom {HEADROOM / GIB:.0f} GiB"
        )

    def require(self, floor: int) -> int:
        """The whole budget for one container, or stop when it is below the floor."""
        if self.limit < floor:
            raise BudgetError(f"{self.describe()}; below the {floor / GIB:.1f} GiB floor")
        return self.limit


def parse_size(text: str) -> int:
    """A Docker size such as 1.136GiB or 26.6MB in bytes."""
    match = SIZE.fullmatch(text)
    if not match or match.group(2).upper() not in UNITS:
        raise BudgetError(f"unknown Docker size {text!r}")
    return int(float(match.group(1)) * UNITS[match.group(2).upper()])


def mac_available(vm_stat: str) -> int:
    """Free, file-backed and purgeable memory from vm_stat output, at the page size its header states."""
    page = PAGE_SIZE.search(vm_stat)
    pages = dict(PAGES.findall(vm_stat))
    if not page or len(pages) != 3:
        raise BudgetError("vm_stat output has no page size or lacks free, purgeable or file-backed pages")
    return sum(int(count) for count in pages.values()) * int(page.group(1))


def container_use(stats: str, replacing: str = "") -> list[int]:
    """Each running container's memory use from `docker stats` rows of name and usage, leaving out names starting with
    ``replacing``; a container with no reading yet stops the plan."""
    usage = []
    for line in stats.splitlines():
        name, _, memory = line.strip().partition(" ")
        if not name or (replacing and name.startswith(replacing)):
            continue
        reading = memory.split("/")[0].strip()
        if reading == "--":
            raise BudgetError(f"container {name} has no memory reading yet; it is starting or stopping, so plan again once it runs")
        usage.append(parse_size(reading))
    return usage


def compute(docker_total: int, container_use: list[int], mac_available: int | None, vm_at_cap: bool) -> Budget:
    """The budget: the smaller of Docker's and the host's free memory, each less HEADROOM."""
    used = sum(container_use)
    limit = docker_total - used - HEADROOM
    host = None if vm_at_cap else mac_available
    if host is not None:
        limit = min(limit, host - HEADROOM)
    return Budget(docker_total=docker_total, container_use=used, mac_available=host, limit=limit)


def stack_limits(budget: Budget) -> dict[str, int]:
    """Each local stack service's share of the budget in whole mebibytes, or stop when any share is below its floor."""
    limits = {name: int(budget.limit * share) // MIB * MIB for name, share in STACK_SHARES.items()}
    short = [f"{name} {limits[name] / GIB:.2f} GiB below its {STACK_FLOORS[name] / GIB:.2f} GiB floor" for name in limits if limits[name] < STACK_FLOORS[name]]
    if short:
        raise BudgetError(f"{budget.describe()}; {'; '.join(short)}")
    return limits


def compose_size(size: int) -> str:
    """A size as whole mebibytes with Compose's m suffix."""
    return f"{size // MIB}m"


def compose_override(limits: dict[str, int]) -> str:
    lines = ["# Written by tools/memory_budget.py at each local stack start; ignored by Git. Limits are planned from the memory free then.", "services:"]
    for name, size in limits.items():
        lines += [f"  {name}:", f"    mem_limit: {compose_size(size)}"]
    return "\n".join(lines) + "\n"


def _output(program: str, *args: str) -> str:
    if find_program(program) is None:
        raise BudgetError(f"{program} is not installed")
    result = run_command(program, list(args), timeout=120)
    if result.returncode:
        raise BudgetError(f"{program} {' '.join(args)} failed: {result.stderr.strip()[-200:]}")
    return result.stdout


def _host_available() -> int:
    if find_program("vm_stat") is not None:
        return mac_available(_output("vm_stat"))
    meminfo = Path("/proc/meminfo")
    match = re.search(r"^MemAvailable:\s+(\d+) kB", meminfo.read_text(encoding="utf-8"), re.MULTILINE) if meminfo.exists() else None
    if not match:
        raise BudgetError("neither vm_stat nor /proc/meminfo MemAvailable can be read")
    return int(match.group(1)) * 1024


def _vm_footprint() -> int | None:
    """The Docker VM process's resident memory in bytes, or None when it is not running on this host."""
    if sys.platform != "darwin":
        return None
    for line in _output("ps", "-axo", "rss=,comm=").splitlines():
        rss, _, command = line.strip().partition(" ")
        if command.strip().endswith(VM_PROCESS) and rss.isdigit():
            return int(rss) * 1024
    return None


def current(replacing: str = "") -> Budget:
    """The budget from Docker's total, running containers' current use and the host's available memory.

    Containers whose names start with ``replacing`` are about to be recreated with the new limits, so their use is not
    counted against the budget.
    """
    total = int(_output("docker", "info", "--format", "{{.MemTotal}}").strip())
    usage = container_use(_output("docker", "stats", "--no-stream", "--format", "{{.Name}} {{.MemUsage}}"), replacing)
    footprint = _vm_footprint()
    vm_at_cap = footprint is not None and footprint >= VM_CAP_FRACTION * total
    host = None if vm_at_cap else _host_available()
    return compute(total, usage, host, vm_at_cap)


def write_stack_override(output: Path) -> Budget:
    budget = current(replacing=f"{STACK_PROJECT}-")
    limits = stack_limits(budget)
    temporary = output.with_suffix(".tmp")
    temporary.write_text(compose_override(limits), encoding="utf-8")
    os.replace(temporary, output)
    sys.stderr.write(f"memory: {budget.describe()}; {', '.join(f'{name} {compose_size(size)}' for name, size in limits.items())}\n")
    return budget


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("target", choices=["stack"])
    parser.add_argument("--output", type=Path, required=True, help="the Compose override file to write")
    parser.add_argument("--explain", action="store_true", help="also print the figures as JSON")
    args = parser.parse_args(argv)
    try:
        budget = write_stack_override(args.output)
    except BudgetError as error:
        sys.stderr.write(f"memory budget: {error}\n")
        return 1
    if args.explain:
        sys.stdout.write(json.dumps(budget.record()) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
