from pathlib import Path

from testkit import expect

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_published_images_use_ecr_scannable_manifests() -> None:
    script = (REPO_ROOT / "scripts/infrastructure/push_images.sh").read_text(encoding="utf-8")

    expect.equal(script.count("docker buildx build"), 5)
    expect.equal(script.count("--provenance=false"), 5)
    expect.is_in("update_env_value", script)
    expect.is_in("VITALS_SIMULATOR_IMAGE_TAG DBT_IMAGE_TAG SODA_IMAGE_TAG OPENLINEAGE_COLLECTOR_IMAGE_TAG", script)
    expect.is_in('"$REPO_ROOT/scripts/infrastructure/render_project_config.sh" --env-file "$ENV_FILE"', script)
