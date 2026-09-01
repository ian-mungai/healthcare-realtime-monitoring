from lineage.openlineage.dbt_lineage import emit_s3_dbt_lineage


def emit_dbt_lineage_event(run_state, lineage_run_id: str | None = None) -> str:
    return emit_s3_dbt_lineage(run_state, lineage_run_id)
