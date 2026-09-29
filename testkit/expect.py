"""Test expectations that always run and report both values.

The test suites use these instead of ``assert`` statements: Python removes ``assert`` under ``-O``, which is why Ruff's
S101 rule blocks it. Each check raises ``AssertionError``, so pytest reports a failure exactly as it would for a failed
``assert``. Conditions that also narrow a type, such as ``isinstance`` or ``is not None``, are written as an ``if`` with
``expect.fail``, which type checkers treat as not returning.
"""

from __future__ import annotations

from typing import Any, NoReturn


def fail(message: str) -> NoReturn:
    """Fail the test with ``message``."""
    raise AssertionError(message)


def _described(message: str, detail: str) -> str:
    return f"{message}: {detail}" if message else detail


def equal(actual: object, expected: object, message: str = "") -> None:
    """Fail unless ``actual == expected``."""
    if actual != expected:
        fail(_described(message, f"expected {expected!r}, got {actual!r}"))


def not_equal(actual: object, unexpected: object, message: str = "") -> None:
    """Fail when ``actual == unexpected``."""
    if actual == unexpected:
        fail(_described(message, f"did not expect {unexpected!r}"))


def is_in(item: object, container: Any, message: str = "") -> None:
    """Fail unless ``item in container``."""
    if item not in container:
        fail(_described(message, f"{item!r} not found in {container!r}"))


def not_in(item: object, container: Any, message: str = "") -> None:
    """Fail when ``item in container``."""
    if item in container:
        fail(_described(message, f"{item!r} unexpectedly found in {container!r}"))


def identical(actual: object, expected: object, message: str = "") -> None:
    """Fail unless ``actual is expected``."""
    if actual is not expected:
        fail(_described(message, f"expected {expected!r} (identity), got {actual!r}"))
