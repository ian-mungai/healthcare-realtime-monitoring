from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_foundation_plan_creates_every_output_required_by_application_generation() -> None:
    script = (REPO_ROOT / "scripts" / "infrastructure" / "bootstrap.sh").read_text(encoding="utf-8")
    foundation_block = script.split("  foundation-plan)", maxsplit=1)[1].split("  foundation-apply)", maxsplit=1)[0]

    for target in ("module.network", "module.raw_s3", "module.hapi_ecs", "module.glue", "module.dbt_ecs", "module.soda_ecs"):
        assert f"-target={target}" in foundation_block

    assert '"$REPO_ROOT/scripts/glue/build_lineage_package.sh"' in foundation_block
