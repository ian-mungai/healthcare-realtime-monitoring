import subprocess

from openlineage.client.event_v2 import RunState

from lineage.openlineage.soda_lineage import emit_s3_soda_lineage


def main() -> int:
    lineage_run_id = emit_s3_soda_lineage(RunState.START)

    try:
        result = subprocess.run(["/app/run_soda_contracts.sh"], check=False)

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
