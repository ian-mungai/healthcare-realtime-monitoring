from lineage.openlineage.soda_lineage import emit_s3_soda_lineage


def emit_soda_lineage_event(run_state, lineage_run_id: str | None = None) -> str:
    return emit_s3_soda_lineage(run_state, lineage_run_id)
