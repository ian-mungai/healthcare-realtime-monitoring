from lineage.openlineage.glue_lineage import emit_s3_glue_lineage


def emit_glue_lineage_event(run_state, lineage_run_id: str | None = None) -> str:
    return emit_s3_glue_lineage(run_state, lineage_run_id)
