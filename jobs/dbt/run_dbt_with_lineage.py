import subprocess
import sys

from openlineage.client.event_v2 import RunState

from lineage.openlineage.dbt_lineage import emit_s3_dbt_lineage


def main() -> int:
    lineage_run_id = emit_s3_dbt_lineage(RunState.START)

    try:
        result = subprocess.run(["dbt", *sys.argv[1:]], check=False)

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
