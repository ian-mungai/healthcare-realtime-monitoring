"""Container memory limits computed at launch from the memory free then, never fixed (tools/memory_budget.py).

Docker's memory is shared with other projects' containers, so each launch plans from what is free at that moment: the
smaller of Docker's total less what running containers use and the memory the Mac can give without swapping, each less a
headroom. The local stack splits that budget across its services; the lock compiler gives it to its one container.

Failure modes (written before the code):

1. A Docker size in a unit the parser does not know, or in decimal instead of binary units, is misread: decimal and
   binary units both parse and an unknown unit stops.
2. The Mac's figure counts only free pages, or assumes 4 KiB pages: it adds free, file-backed and purgeable pages and
   reads the page size from the vm_stat header.
3. The Mac's figure is used after the Docker VM already holds its full allocation, so it double-counts memory Docker
   has: the Mac's figure is skipped then.
4. A budget below a service's floor falls back to a fixed limit: it stops and names the figures.
5. The services' limits add up to more than the budget.
6. Compose misreads the limit's unit: limits are written as whole mebibytes with Compose's "m" suffix.
7. A container that is starting or stopping has no reading yet ("--") and counts as using nothing: it stops and names
   the container, so the next start reads it once it runs.
8. The stack's own containers, about to be recreated with the new limits, count against the budget: they are left out.
"""

from __future__ import annotations

import pytest

from testkit import expect
from tools import memory_budget

GIB = 1024**3
MIB = 1024**2
VM_STAT = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                                    29232.
Pages active:                                 579044.
Pages purgeable:                                4552.
File-backed pages:                            451916.
"""


def test_docker_sizes_parse_in_decimal_and_binary_units() -> None:
    expect.equal(memory_budget.parse_size("627MiB"), 627 * MIB)
    expect.equal(memory_budget.parse_size("1.5GiB"), int(1.5 * GIB))
    expect.equal(memory_budget.parse_size("26.64MB"), 26_640_000)
    expect.equal(memory_budget.parse_size("0B"), 0)
    with pytest.raises(memory_budget.BudgetError, match="unknown Docker size"):
        memory_budget.parse_size("12 parsecs")


def test_the_mac_figure_adds_free_file_backed_and_purgeable_pages_at_the_header_page_size() -> None:
    expect.equal(memory_budget.mac_available(VM_STAT), (29232 + 4552 + 451916) * 16384)
    with pytest.raises(memory_budget.BudgetError, match="vm_stat"):
        memory_budget.mac_available("Pages free: 10.\n")


def test_the_budget_is_the_smaller_figure_less_headroom() -> None:
    docker_side = memory_budget.compute(docker_total=32 * GIB, container_use=[GIB], mac_available=8 * GIB, vm_at_cap=False)
    expect.equal(docker_side.limit, 8 * GIB - memory_budget.HEADROOM)
    roomy_mac = memory_budget.compute(docker_total=10 * GIB, container_use=[GIB, GIB], mac_available=40 * GIB, vm_at_cap=False)
    expect.equal(roomy_mac.limit, 8 * GIB - memory_budget.HEADROOM)


def test_the_mac_figure_is_skipped_once_the_docker_vm_holds_its_allocation() -> None:
    budget = memory_budget.compute(docker_total=32 * GIB, container_use=[GIB], mac_available=GIB, vm_at_cap=True)
    expect.equal(budget.limit, 31 * GIB - memory_budget.HEADROOM)
    expect.equal(budget.record()["mac_available"], None)


def test_stack_limits_stay_within_the_budget_and_use_compose_mebibytes() -> None:
    budget = memory_budget.compute(docker_total=32 * GIB, container_use=[], mac_available=7 * GIB, vm_at_cap=False)

    limits = memory_budget.stack_limits(budget)

    expect.equal(sorted(limits), sorted(memory_budget.STACK_SHARES))
    expect.equal(sum(limits.values()) <= budget.limit, True, f"{limits} exceed {budget.limit}")
    expect.equal(all(value % MIB == 0 for value in limits.values()), True)
    expect.equal(memory_budget.compose_size(2 * GIB + MIB), "2049m")


def test_a_budget_below_a_floor_stops_with_the_figures() -> None:
    small = memory_budget.compute(docker_total=32 * GIB, container_use=[], mac_available=4 * GIB, vm_at_cap=False)
    with pytest.raises(memory_budget.BudgetError, match="hapi.*floor"):
        memory_budget.stack_limits(small)
    with pytest.raises(memory_budget.BudgetError, match="GiB"):
        memory_budget.compute(docker_total=32 * GIB, container_use=[], mac_available=GIB, vm_at_cap=False).require(memory_budget.LOCK_FLOOR)


def test_container_use_skips_the_stack_and_stops_on_a_missing_reading() -> None:
    stats = "other-db-1 26.64MiB / 31.29GiB\nhealthcare-realtime-local-hapi-1 1.5GiB / 31.29GiB\nother-app-1 1GiB / 31.29GiB\n"
    expect.equal(memory_budget.container_use(stats, replacing="healthcare-realtime-local-"), [int(26.64 * MIB), GIB])
    with pytest.raises(memory_budget.BudgetError, match="other-dbt-run-1"):
        memory_budget.container_use("other-dbt-run-1 -- / --\n", replacing="")
