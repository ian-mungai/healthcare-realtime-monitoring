from lineage.openlineage.athena_lineage import emit_s3_athena_lineage


def emit_athena_lineage_event(run_state, lineage_run_id: str | None = None) -> str:
    return emit_s3_athena_lineage(run_state, lineage_run_id)
