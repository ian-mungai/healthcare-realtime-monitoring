"""A program kept running for the length of a block, such as an SSM port forward (tools.process.background).

Failure modes (written before the code):

1. The program outlives the block, as when the block raises: it is stopped on every exit.
2. The program ignores the polite stop: it is killed after a grace period.
3. The program's own children (session-manager-plugin under the AWS CLI) outlive it: the whole process group stops.
4. The program exits early, so the caller waits on a port that never opens: the caller can see it has exited.
"""

from __future__ import annotations

import os
import sys
import time

import pytest

from testkit import expect
from tools.process import background

# Starts a child that also sleeps, prints both process IDs and ignores SIGTERM when asked to.
CHILDREN = """
import os, signal, subprocess, sys, time
if len(sys.argv) > 1:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
print(os.getpid(), child.pid, flush=True)
time.sleep(60)
"""


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def wait_gone(*pids: int, seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not any(alive(pid) for pid in pids):
            return True
        time.sleep(0.1)
    return False


def started(process) -> tuple[int, int]:
    line = process.stdout.readline().split()
    return int(line[0]), int(line[1])


def test_the_program_and_its_children_stop_when_the_block_raises() -> None:
    with pytest.raises(RuntimeError), background(sys.executable, ["-c", CHILDREN]) as process:
        parent, child = started(process)
        raise RuntimeError("the caller failed")

    expect.equal(wait_gone(parent, child), True)


def test_a_program_that_ignores_the_stop_is_killed() -> None:
    with background(sys.executable, ["-c", CHILDREN, "ignore"], grace_seconds=1) as process:
        parent, child = started(process)

    expect.equal(wait_gone(parent, child), True)


def test_an_early_exit_is_visible_to_the_caller() -> None:
    with background(sys.executable, ["-c", "raise SystemExit(3)"]) as process:
        expect.equal(process.wait(timeout=10), 3)
