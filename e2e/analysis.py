"""Run the pre-specified analysis end to end on both arms: check the frozen plan, execute the notebook, write the report.

Usage: python -m e2e.analysis --plan-sha256 <PLAN_SHA256> [--plan plans/analysis-plan.md]

Run it after both arms' local warehouses are built. The plan stays local and is frozen by its
SHA-256, recorded when it was frozen; the run stops before reading any data if the file differs. For the study and the
null-control arm it executes notebooks/model_comparison.ipynb headless with nbconvert, keeps the executed notebook and
results.json under artifacts/e2e/analysis/<RUN_ID>/<ARM>/ and checks that each run covered the plan's analysis set.
The hypothesis decisions are results, not checks: they are recorded as evidence, the null arm's as false positives.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

from e2e.report import ARTIFACT_ROOT, ROOT, Blocked, Report
from jobs.analysis import data
from jobs.analysis.run import BOOTSTRAP_RESAMPLES, FITTED, REFERENCE
from tools.process import find_program, run_command

NOTEBOOK = ROOT / "notebooks" / "model_comparison.ipynb"
ARMS = ("study", "null_control")
# The plan's analysis set: 600 encounters per arm less those without a complete NEWS2 (waveform record bidmc19n).
ENCOUNTERS_PER_ARM = 600
EXPECTED_SPLIT_GROUPS = 52
# The plan's recorded deviations (plans/analysis-plan.md, Deviations); results that depend on a post-hoc one say so.
DEVIATIONS = {
    "1": "calibration values corrected after the dropout fix; before any study result",
    "2": "H1 (a) is a GEE score test of the 14 vital terms; before any study result",
    "3": "minute models use the five continuous vitals; POST HOC: the GEE model, H1 (b) and the Holm adjustment of H2 depend on it",
}
PURPOSE = "The frozen analysis plan runs unchanged on the study and the null-control arm and records every pre-specified result."
LIMITS = (
    "Runs on the local Postgres warehouses of the 100-patient batches, not on AWS. The label is a synthetic proxy and "
    "the planted precursor makes it predictable to a chosen degree, so results show how well each method recovers a "
    "planted signal, not clinical performance. The bootstrap holds out-of-fold scores fixed and does not refit models."
)
REPRODUCE = (
    "Build both arms' warehouses, then run `.venv/bin/python -m e2e.analysis --plan-sha256 <PLAN_SHA256>` with the hash recorded when the plan was frozen."
)


def run_arm(report: Report, signal: str, folder: Path, plan: Path, plan_sha256: str) -> dict:
    """Execute the notebook for one arm and return its results."""
    arm_folder = folder / signal
    arm_folder.mkdir(parents=True, exist_ok=True)
    results_path = arm_folder / "results.json"
    jupyter = find_program(str(ROOT / ".venv" / "bin" / "jupyter"))
    if jupyter is None:
        raise Blocked("JupyterLab is not installed in .venv; install requirements_dev.txt")
    environment = {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "ANALYSIS_ROOT": str(ROOT),
        "ANALYSIS_SIGNAL": signal,
        "ANALYSIS_PLAN": str(plan.relative_to(ROOT)),
        "ANALYSIS_PLAN_SHA256": plan_sha256,
        "ANALYSIS_RESULTS": str(results_path),
    }
    args = ["nbconvert", "--to", "notebook", "--execute", "--ExecutePreprocessor.timeout=3600", "--output-dir", str(arm_folder), str(NOTEBOOK)]
    result = run_command(jupyter, args, cwd=ROOT, timeout=7200, env=environment)
    report.check(
        f"{signal}: notebook runs", "exit code 0", f"{result.returncode} {result.stderr.strip()[-200:] if result.returncode else ''}", result.returncode == 0
    )
    if result.returncode != 0:
        return {}
    results = json.loads(results_path.read_text(encoding="utf-8"))
    analysis_set = results["analysis_set"]
    report.check(
        f"{signal}: analysis set",
        f"{ENCOUNTERS_PER_ARM} encounters less those without NEWS2, {EXPECTED_SPLIT_GROUPS} split groups, 15 minutes each",
        f"{analysis_set['encounters']} + {analysis_set['excluded_without_news2']} excluded, "
        f"{analysis_set['split_groups']} groups, {analysis_set['minute_rows']} minute rows",
        analysis_set["encounters"] + analysis_set["excluded_without_news2"] == ENCOUNTERS_PER_ARM
        and analysis_set["split_groups"] == EXPECTED_SPLIT_GROUPS
        and analysis_set["minute_rows"] == 15 * analysis_set["encounters"],
    )
    keys = [row["encounter_key"] for row in results["scores"]]
    # A model that failed to fit leaves NaN, which JSON keeps as a number; only finite scores count.
    complete = all(isinstance(row[name], int | float) and math.isfinite(row[name]) for row in results["scores"] for name in (REFERENCE, *FITTED))
    report.check(
        f"{signal}: every encounter scored once by every model",
        f"{analysis_set['encounters']} unique encounters with 4 scores each",
        f"{len(set(keys))} unique of {len(keys)}, complete {complete}",
        len(keys) == len(set(keys)) == analysis_set["encounters"] and complete,
    )
    skipped = results["primary"]["bootstrap"]["skipped"]
    report.check(
        f"{signal}: bootstrap resamples usable", f"under 1% of {BOOTSTRAP_RESAMPLES} skipped", f"{skipped} skipped", skipped < BOOTSTRAP_RESAMPLES / 100
    )
    report.check(f"{signal}: plan hash recorded", plan_sha256[:12], str(results.get("plan_sha256", ""))[:12], results.get("plan_sha256") == plan_sha256)
    return results


def summary(results: dict) -> dict:
    primary = results["primary"]
    return {
        "auc": {name: round(value, 4) for name, value in primary["auc"].items()},
        "auc_interval": {name: [round(low, 4), round(high, 4)] for name, (low, high) in primary["auc_interval"].items()},
        "versus_news2": {name: {key: round(value, 6) for key, value in values.items()} for name, values in primary["comparisons"].items()},
        "h1": {"p_value": results["h1"]["p_value"]},
        "h3_holm": {name: test["holm_p_value"] for name, test in results["h3"].items()},
        "h3_estimates": {name: test["estimates"] for name, test in results["h3"].items()},
        "decisions": results["decisions"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--plan-sha256", required=True, help="the SHA-256 recorded when the analysis plan was frozen")
    parser.add_argument("--plan", type=Path, default=ROOT / "plans" / "analysis-plan.md")
    args = parser.parse_args(argv)
    report = Report(scenario="analysis", purpose=PURPOSE, limits=LIMITS, reproduce=REPRODUCE)
    folder = ARTIFACT_ROOT / report.scenario / f"{report.started_at_utc.replace(':', '').replace('-', '')}_{report.run_id}"
    error: BaseException | None = None
    try:
        plan = args.plan.resolve()
        if not plan.is_file():
            raise Blocked(f"no analysis plan at {plan.relative_to(ROOT) if plan.is_relative_to(ROOT) else plan.name}")
        try:
            data.check_plan(plan, args.plan_sha256)
            report.check("Plan matches its frozen hash", args.plan_sha256[:12], args.plan_sha256[:12], True)
        except data.AnalysisError as mismatch:
            report.check("Plan matches its frozen hash", args.plan_sha256[:12], str(mismatch), False)
            raise
        report.parameters = {"plan_sha256": args.plan_sha256, "arms": list(ARMS), "resamples": BOOTSTRAP_RESAMPLES}
        report.evidence["plan_deviations"] = DEVIATIONS
        for signal in ARMS:
            results = run_arm(report, signal, folder, plan, args.plan_sha256)
            if results:
                report.evidence[signal] = summary(results)
                if signal == "null_control":
                    report.evidence["null_control_false_positives"] = [name for name in ("h1", "h2", "h3") if results["decisions"][name]]
    except Exception as failure:
        error = failure
    report.finish(error)
    out = report.write()
    sys.stdout.write(f"analysis: {report.status} ({out.relative_to(ROOT)}/report.md)\n")
    return 0 if report.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
