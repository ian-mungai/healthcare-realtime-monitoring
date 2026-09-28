from openlineage.client.event_v2 import RunState

from lineage.openlineage.soda_lineage import emit_s3_soda_lineage
from tools.process import run_command

# Contract checks finish well inside this limit; the MWAA task timeout is longer.
JOB_TIMEOUT_SECONDS = 3600


def main() -> int:
    lineage_run_id = emit_s3_soda_lineage(RunState.START)

    try:
        result = run_command("/app/run_soda_contracts.sh", [], timeout=JOB_TIMEOUT_SECONDS, capture=False)

        if result.returncode != 0:
            emit_s3_soda_lineage(RunState.FAIL, lineage_run_id)
            return result.returncode

        emit_s3_soda_lineage(RunState.COMPLETE, lineage_run_id)

        return 0

    except Exception:
        emit_s3_soda_lineage(RunState.FAIL, lineage_run_id)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
