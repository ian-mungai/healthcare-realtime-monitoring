from __future__ import annotations

import re
from pathlib import Path

from services.vitals_stream_processor import handler
from testkit import expect

REPO_ROOT = Path(__file__).resolve().parents[2]
PROCESSOR_MODULE_PATH = REPO_ROOT / "infra/modules/realtime_processor/main.tf"


def allowed_metric_namespaces() -> set[str]:
    module = PROCESSOR_MODULE_PATH.read_text(encoding="utf-8")
    statement = re.search(r'sid\s*=\s*"PublishPipelineMetrics".*?values\s*=\s*\[(?P<values>[^\]]*)\]', module, re.DOTALL)
    if statement is None:
        expect.fail("expected: a PublishPipelineMetrics statement with a cloudwatch:namespace condition")
    return set(re.findall(r'"([^"]+)"', statement.group("values")))


def test_processor_role_allows_every_namespace_the_handler_publishes() -> None:
    # Load-test metrics were denied in the 2026-10-06 proof session because only the live namespace was allowed.
    expect.equal(allowed_metric_namespaces(), {handler.METRIC_NAMESPACE, handler.LOAD_TEST_METRIC_NAMESPACE})
