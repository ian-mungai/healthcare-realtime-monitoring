"""Check the early-warning endpoint on AWS: NEWS2 from the live cache and the real-time model score equal their references.

Usage: python -m e2e.aws_early_warning [--env-file PATH]

Run it after a live simulator run whose encounters lasted past their 15-minute feature window, and after the daily
workflow has batch-scored those encounters with the approved model. For every cohort patient it reads
GET /patients/{id}/early-warning and the latest vitals, checks NEWS2 against services/news2.py on the same vitals and,
for each scored encounter, checks the live score against the batch score in Athena. Every run writes report.json and
report.md under artifacts/e2e/aws_early_warning/, passed, failed or blocked.

Failure modes (written before the code):

1. NEWS2 is compared with vitals that changed between the two requests: a patient is compared only when the vitals
   read before and after the endpoint call are the same.
2. A score computed from a partial window is accepted: only encounters the endpoint reports as scored are compared.
3. The live and batch scores are compared for different encounters or model versions: the batch score is read for the
   endpoint's encounter ID and model version.
4. No encounter is scored or batch-scored yet, and the run passes on nothing: it is blocked and says which is missing.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from string import Template
from typing import Any

from e2e.context import DEPLOYMENT_DEFAULTS, ROOT, Context, load_context
from e2e.report import Blocked, Report
from services.early_warning.scoring import news2_summary

# Athena keeps a probability as a double; both sides print it to 17 significant digits at most.
SCORE_TOLERANCE = 1e-9
BATCH_SCORE = Template(
    "select predictions.deterioration_probability from $ml.$predictions as predictions "
    "inner join $dbt.$encounters as encounters on predictions.encounter_key = encounters.encounter_key "
    "where encounters.encounter_id = ? and predictions.model_version = ?"
)
PURPOSE = "The early-warning endpoint's NEWS2 equals services/news2.py on the cached vitals and its live model score equals the batch score."
LIMITS = (
    "Covers the cohort's current encounters only. The score is a synthetic deterioration proxy's probability from a "
    "planted-signal simulation, not a clinical risk; NEWS2 is computed, not clinically validated."
)
REPRODUCE = (
    "Run the simulator past each encounter's 15-minute window, run the daily workflow so it batch-scores the encounters, "
    "then run `.venv/bin/python -m e2e.aws_early_warning`."
)


def batch_score(context: Context, encounter_id: str, model_version: str) -> float | None:
    names = json.loads(DEPLOYMENT_DEFAULTS.read_text(encoding="utf-8"))["terraform"]
    query = BATCH_SCORE.substitute(
        ml=names["ml_database_name"],
        predictions=names["ml_predictions_published_table_name"],
        dbt=names["dbt_database_name"],
        encounters=names["dbt_dim_encounter_table_name"],
    )
    rows = context.athena_rows(query, names["dbt_database_name"], [f"'{encounter_id}'", f"'{model_version}'"])
    return float(rows[0][0]) if rows and rows[0][0] is not None else None


def get_json(context: Context, url: str) -> dict[str, Any] | None:
    response = context.get(url)
    return response.json() if response.status_code == 200 else None


def run(report: Report, context: Context) -> None:
    base = str(context.output("vitals_api_endpoint")).rstrip("/")
    compared_news2 = scored = compared_scores = 0
    missing_batch = []
    for patient_id in context.patient_ids:
        before = get_json(context, context.vitals_url(patient_id))
        warning = get_json(context, f"{base}/patients/{patient_id}/early-warning")
        after = get_json(context, context.vitals_url(patient_id))
        if warning is None or before is None:
            report.check(f"{patient_id}: endpoint answers", "HTTP 200 with live vitals", "no live vitals or no answer", False)
            continue
        if before == after:
            compared_news2 += 1
            expected = news2_summary(before)
            report.check(
                f"{patient_id}: NEWS2 equals services/news2.py",
                f"total {expected['total']}, missing {expected['missing']}",
                f"total {warning['news2']['total']}, missing {warning['news2']['missing']}",
                warning["news2"] == json.loads(json.dumps(expected)),
            )
        model = warning["model"]
        if model["status"] != "scored":
            continue
        scored += 1
        expected_score = batch_score(context, warning["encounter_id"], model["model_version"])
        if expected_score is None:
            missing_batch.append(patient_id)
            continue
        compared_scores += 1
        report.check(
            f"{patient_id}: live score equals the batch score",
            f"{expected_score:.12f} ({model['model_version']})",
            f"{model['probability']:.12f} from {model['readings']} readings",
            math.isclose(model["probability"], expected_score, rel_tol=0, abs_tol=SCORE_TOLERANCE),
        )
    report.evidence = {"news2_compared": compared_news2, "scored": scored, "scores_compared": compared_scores, "without_batch_score": missing_batch}
    if not compared_news2:
        raise Blocked("the vitals changed during every comparison; stop the simulator and run again")
    if not scored:
        raise Blocked("no current encounter is scored yet; run the simulator past the 15-minute window")
    if not compared_scores:
        raise Blocked("no scored encounter has a batch score yet; run the daily workflow first")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--env-file", type=Path, default=Path(os.getenv("PROJECT_ENV_FILE") or ROOT / ".env"))
    args = parser.parse_args(argv)
    report = Report(scenario="aws_early_warning", purpose=PURPOSE, limits=LIMITS, reproduce=REPRODUCE)
    error: BaseException | None = None
    try:
        run(report, load_context(args.env_file))
    except Exception as failure:
        error = failure
    report.finish(error)
    folder = report.write()
    sys.stdout.write(f"aws_early_warning: {report.status} ({folder.relative_to(ROOT)}/report.md)\n")
    return 0 if report.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
