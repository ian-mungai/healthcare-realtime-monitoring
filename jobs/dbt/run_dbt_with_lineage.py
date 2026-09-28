import sys

from openlineage.client.event_v2 import RunState

from lineage.openlineage.dbt_lineage import emit_s3_dbt_lineage
from tools.process import run_command

# dbt builds and scoring runs finish well inside this limit; the MWAA task timeout is longer.
JOB_TIMEOUT_SECONDS = 3600


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "score-ml":
        return run_command(sys.executable, ["-m", "jobs.ml.score_logistic_regression", *sys.argv[2:]], timeout=JOB_TIMEOUT_SECONDS, capture=False).returncode

    lineage_run_id = emit_s3_dbt_lineage(RunState.START)

    try:
        result = run_command("dbt", sys.argv[1:], timeout=JOB_TIMEOUT_SECONDS, capture=False)

        if result.returncode != 0:
            emit_s3_dbt_lineage(RunState.FAIL, lineage_run_id)
            return result.returncode

        emit_s3_dbt_lineage(RunState.COMPLETE, lineage_run_id)

        return 0

    except Exception:
        emit_s3_dbt_lineage(RunState.FAIL, lineage_run_id)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
