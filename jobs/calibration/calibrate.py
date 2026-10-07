"""Calibrate the planted signal on a separate seed so NEWS2 and the model reach their target discrimination.

Usage: python -m jobs.calibration.calibrate [--write]

The study needs a known, moderate signal: a logistic regression on the warehouse's vital-features-v3 should reach an
area under the ROC curve (AUC) of about 0.80, and NEWS2 from the end of the feature window about 0.70, while the null
control stays near 0.50. This job generates the batch in memory for CALIBRATION_SEED, never the study seed, without
writing to HAPI or disk, so the study's results stay unseen until the analysis plan is committed (step 5). It scales
the configured effect sizes (trend scale) and the supplemental-oxygen and new-confusion probabilities (event scale)
over a grid, scores each point, picks the one closest to both targets and checks the null control there. For RQ3 it
estimates the age 65+ x deterioration interaction on the heart-rate rise and its power over ten more calibration seeds. The model's
AUC comes from grouped 5-fold cross-validation, grouped by waveform split group like the warehouse's split. --write
records the chosen values in config/planted_signal.json; scales are relative to the configured signal, so the
version goes up only when the values change. Every run writes report.json and
report.md under artifacts/e2e/calibration/. Settings come from the environment like the batch generator: COHORT_SIZE,
FHIR_RESOURCE_MAP_FILE.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from e2e.report import ROOT, Blocked, Report
from jobs.batch_vitals import generate
from jobs.calibration.features import FEATURE_COLUMNS, encounter_features
from services.vitals_simulator.app.fhir.mapping import get_patient_cohort
from services.vitals_simulator.app.simulation.precursor import is_65_plus, load_planted_signal
from services.vitals_simulator.app.simulation.scenario import DETERIORATION_SCENARIO
from services.vitals_simulator.app.synthea.blood_pressure import load_synthea_blood_pressure_readings

CALIBRATION_SEED = "2718281"
TARGETS = {"model": 0.80, "news2": 0.70}
TOLERANCE = 0.03
NULL_TOLERANCE = 0.05
TREND_SCALES = (0.5, 0.75, 1.0, 1.5, 2.0, 3.0)
EVENT_SCALES = (0.0, 0.5, 1.0, 2.0, 3.0)
FOLDS = 5
# RQ3: the planted age 65+ effect must be detectable. Power is the share of extra calibration seeds whose 95% CI for the
# age x deterioration interaction on the heart-rate rise lies below 0.
POWER_SEEDS = tuple(f"{CALIBRATION_SEED}{index}" for index in range(1, 11))
POWER_TARGET = 0.8
# The null control's mean interaction over the seeds must stay this close to 0 (no built-in age bias).
NULL_BIAS_BPM = 0.5
BOOTSTRAP_RESAMPLES = 1000
# Heart-rate rise: the last minute of the feature window minus the 5 minutes before the planted ramp starts.
RISE_LATE_SECONDS = (840, 900)
RISE_EARLY_SECONDS = (0, 300)
CONFIG_PATH = ROOT / "config" / "planted_signal.json"
# Stable namespace for the in-memory encounter IDs, so a rerun builds the same records.
OFFLINE_NAMESPACE = uuid.UUID("8d3f2a61-7c4e-5b19-a0d2-3e6f9c1b4a57")
PURPOSE = "The planted signal, calibrated on a separate seed, gives NEWS2 about 0.70 and the model about 0.80, with the null control near 0.50."
LIMITS = (
    "Calibrates on one calibration seed with the same 100 patients and waveform records as the study, so study results "
    "will differ by sampling. The model is a logistic regression on vital-features-v3 only; the study's models in step 5 "
    "also use trends. The study seed's discrimination is not computed here."
)
REPRODUCE = "Run `.venv/bin/python -m jobs.calibration.calibrate` with COHORT_SIZE and FHIR_RESOURCE_MAP_FILE exported."


def scaled_signal(base: dict[str, Any], trend_scale: float, event_scale: float) -> dict[str, Any]:
    """The signal with effect sizes times trend_scale and oxygen and confusion probabilities times event_scale."""
    signal = copy.deepcopy(base)
    # Rounded so a rerun writes the same file without floating-point noise.
    for spec in signal["effects"].values():
        spec["mean"] = round(spec["mean"] * trend_scale, 6)
        spec["sd"] = round(spec["sd"] * trend_scale, 6)
    for event in ("supplemental_oxygen", "new_confusion"):
        signal[event]["probability"] = round(min(1.0, signal[event]["probability"] * event_scale), 6)
    return signal


def dataset(settings: generate.BatchSettings, cohort: list, bp_readings: list, fetch: Any, signal: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per encounter: features, NEWS2, label and split group, built in memory."""
    rows = []
    for encounter in generate.plan_encounters(settings, cohort, bp_readings, fetch, signal=signal):
        encounter_id = str(uuid.uuid5(OFFLINE_NAMESPACE, f"{generate.run_identifier(settings, encounter.run)}:{encounter.context.hapi_patient_id}"))
        records = list(generate.encounter_records(settings, encounter, encounter_id, Counter()))
        rows.append(
            {
                **encounter_features(records),
                "label": int(encounter.scenario == DETERIORATION_SCENARIO),
                "group": encounter.split_group,
                "patient": encounter.context.hapi_patient_id,
                "age_65_plus": is_65_plus((encounter.context.admission_profile or {})["birth_date"], encounter.started_at),
                "hr_rise": heart_rate_rise(records),
            }
        )
    return rows


def heart_rate_rise(records: list[dict[str, Any]]) -> float | None:
    """Mean heart rate late in the feature window minus the mean before the planted ramp can start."""
    timed = sorted(((datetime.fromisoformat(record["event_timestamp"]), record) for record in records), key=lambda pair: pair[0])
    if not timed:
        return None
    start = timed[0][0]
    windows: dict[str, list[float]] = {"early": [], "late": []}
    for when, record in timed:
        if record.get("heart_rate") is None:
            continue
        elapsed = (when - start).total_seconds()
        if RISE_EARLY_SECONDS[0] <= elapsed < RISE_EARLY_SECONDS[1]:
            windows["early"].append(record["heart_rate"])
        elif RISE_LATE_SECONDS[0] <= elapsed < RISE_LATE_SECONDS[1]:
            windows["late"].append(record["heart_rate"])
    if not windows["early"] or not windows["late"]:
        return None
    return float(np.mean(windows["late"]) - np.mean(windows["early"]))


def rq3_interaction(rows: list[dict[str, Any]], resamples: int = BOOTSTRAP_RESAMPLES) -> dict[str, float]:
    """The age 65+ x deterioration interaction on the heart-rate rise, with a 95% CI from a patient-clustered bootstrap."""
    usable = [row for row in rows if row["hr_rise"] is not None]
    patients = sorted({row["patient"] for row in usable})
    by_patient = {patient: [row for row in usable if row["patient"] == patient] for patient in patients}

    def fit(sample: list[dict[str, Any]]) -> float:
        label = np.array([row["label"] for row in sample], dtype=float)
        older = np.array([float(row["age_65_plus"]) for row in sample])
        design = np.column_stack([np.ones(len(sample)), label, older, label * older])
        coefficients, *_ = np.linalg.lstsq(design, np.array([row["hr_rise"] for row in sample]), rcond=None)
        return float(coefficients[3])

    rng = np.random.default_rng(int.from_bytes(hashlib.sha256(b"rq3-bootstrap").digest()[:8], "big"))
    estimates = [fit([row for patient in rng.choice(patients, size=len(patients)) for row in by_patient[patient]]) for _ in range(resamples)]
    lower, upper = np.percentile(estimates, [2.5, 97.5])
    return {"estimate": round(fit(usable), 4), "lower": round(float(lower), 4), "upper": round(float(upper), 4)}


def evaluate(rows: list[dict[str, Any]]) -> dict[str, float]:
    """The model's grouped cross-validated AUC and NEWS2's AUC on the same encounters."""
    features = np.array([[math.nan if row[column] is None else row[column] for column in FEATURE_COLUMNS] for row in rows], dtype=float)
    labels = np.array([row["label"] for row in rows])
    groups = np.array([row["group"] for row in rows])
    model = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(max_iter=2000))
    probabilities = cross_val_predict(model, features, labels, groups=groups, cv=GroupKFold(n_splits=FOLDS), method="predict_proba")[:, 1]
    scored = [(row["news2"], row["label"]) for row in rows if row["news2"] is not None]
    news2_auc = roc_auc_score([label for _score, label in scored], [score for score, _label in scored])
    return {"model": round(float(roc_auc_score(labels, probabilities)), 4), "news2": round(float(news2_auc), 4), "news2_rows": len(scored)}


def distance(result: dict[str, float]) -> float:
    return math.hypot(result["model"] - TARGETS["model"], result["news2"] - TARGETS["news2"])


def write_config(trend_scale: float, event_scale: float, chosen: dict[str, float], null: dict[str, float], rq3: dict[str, Any], report_path: Path) -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    base_version = config["version"]
    config["signals"]["study"] = scaled_signal(config["signals"]["study"], trend_scale, event_scale)
    # Scales are relative to the configured signal, so a rerun that keeps it (1.0 and 1.0) keeps the version.
    if (trend_scale, event_scale) != (1.0, 1.0):
        prefix, number = base_version.rsplit("-v", 1)
        config["version"] = f"{prefix}-v{int(number) + 1}"
    config["calibration"] = {
        "seed": CALIBRATION_SEED,
        "base_version": base_version,
        "method": (
            "grid over trend and event scales; model AUC from grouped 5-fold cross-validated logistic regression on "
            "vital-features-v3; NEWS2 AUC from the last feature-window values"
        ),
        "targets": TARGETS,
        "trend_scale": trend_scale,
        "event_scale": event_scale,
        "achieved": chosen,
        "null_control": null,
        "rq3": rq3,
        "report": str(report_path.relative_to(ROOT)),
    }
    CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--write", action="store_true", help="record the chosen values in config/planted_signal.json")
    args = parser.parse_args(argv)
    report = Report(scenario="calibration", purpose=PURPOSE, limits=LIMITS, reproduce=REPRODUCE)
    error: BaseException | None = None
    choice: tuple[float, float, dict[str, float], dict[str, float], dict[str, Any]] | None = None
    try:
        settings = generate.BatchSettings(seed=CALIBRATION_SEED, start=datetime.fromisoformat(generate.DEFAULT_START))
        if settings.seed == generate.DEFAULT_SEED:
            raise Blocked("the calibration seed must differ from the study seed")
        cohort, bp_readings, fetch = get_patient_cohort(), load_synthea_blood_pressure_readings(), generate.cached_fetch(generate.DEFAULT_RECORD_CACHE)
        base, null_signal = load_planted_signal("study"), load_planted_signal("null_control")
        report.parameters = {"seed": CALIBRATION_SEED, "base_version": base["version"], "targets": TARGETS, "folds": FOLDS}
        grid = []
        for trend_scale in TREND_SCALES:
            for event_scale in EVENT_SCALES:
                result = evaluate(dataset(settings, cohort, bp_readings, fetch, scaled_signal(base, trend_scale, event_scale)))
                grid.append({"trend_scale": trend_scale, "event_scale": event_scale, **result})
                sys.stdout.write(f"trend x{trend_scale} event x{event_scale}: model {result['model']:.3f}, NEWS2 {result['news2']:.3f}\n")
        best = min(grid, key=distance)
        chosen = {"model": best["model"], "news2": best["news2"]}
        chosen_signal = scaled_signal(base, best["trend_scale"], best["event_scale"])
        null_rows = dataset(settings, cohort, bp_readings, fetch, null_signal)
        null = evaluate(null_rows)
        rq3 = rq3_interaction(dataset(settings, cohort, bp_readings, fetch, chosen_signal))
        null_rq3 = rq3_interaction(null_rows)
        power_runs: list[dict[str, Any]] = []
        null_runs: list[dict[str, Any]] = []
        for seed in POWER_SEEDS:
            seed_settings = generate.BatchSettings(seed=seed, start=settings.start)
            power_runs.append({"seed": seed, **rq3_interaction(dataset(seed_settings, cohort, bp_readings, fetch, chosen_signal))})
            null_runs.append({"seed": seed, **rq3_interaction(dataset(seed_settings, cohort, bp_readings, fetch, null_signal))})
        power = sum(1 for run in power_runs if float(run["upper"]) < 0) / len(power_runs)
        false_positive_rate = sum(1 for run in null_runs if float(run["upper"]) < 0 or float(run["lower"]) > 0) / len(null_runs)
        null_mean = round(float(np.mean([float(run["estimate"]) for run in null_runs])), 4)
        rq3_summary = {
            "calibration_seed": rq3,
            "null_control": null_rq3,
            "power": power,
            "null_false_positive_rate": false_positive_rate,
            "null_mean_estimate": null_mean,
            "seeds": len(power_runs),
        }
        choice = (best["trend_scale"], best["event_scale"], chosen, {"model": null["model"], "news2": null["news2"]}, rq3_summary)
        report.check(
            "Model AUC near its target", f"{TARGETS['model']} +/- {TOLERANCE}", f"{chosen['model']}", abs(chosen["model"] - TARGETS["model"]) <= TOLERANCE
        )
        report.check(
            "NEWS2 AUC near its target", f"{TARGETS['news2']} +/- {TOLERANCE}", f"{chosen['news2']}", abs(chosen["news2"] - TARGETS["news2"]) <= TOLERANCE
        )
        report.check("Model beats NEWS2", "model AUC above NEWS2 AUC", f"{chosen['model']} vs {chosen['news2']}", chosen["model"] > chosen["news2"])
        report.check("Null control model AUC near 0.5", f"0.5 +/- {NULL_TOLERANCE}", f"{null['model']}", abs(null["model"] - 0.5) <= NULL_TOLERANCE)
        report.check("Null control NEWS2 AUC near 0.5", f"0.5 +/- {NULL_TOLERANCE}", f"{null['news2']}", abs(null["news2"] - 0.5) <= NULL_TOLERANCE)
        report.check(
            "RQ3 age effect detectable",
            f"95% CI of the age 65+ x deterioration heart-rate interaction below 0 in at least {POWER_TARGET:.0%} of {len(POWER_SEEDS)} seeds",
            f"{power:.0%}; calibration seed {rq3['estimate']} bpm ({rq3['lower']} to {rq3['upper']})",
            power >= POWER_TARGET,
        )
        report.check(
            "Null control shows no age effect",
            f"95% CI includes 0 on the calibration seed; mean estimate over {len(POWER_SEEDS)} seeds within {NULL_BIAS_BPM} bpm of 0",
            f"{null_rq3['estimate']} bpm ({null_rq3['lower']} to {null_rq3['upper']}); mean {null_mean} bpm; {false_positive_rate:.0%} of seeds exclude 0",
            null_rq3["lower"] <= 0 <= null_rq3["upper"] and abs(null_mean) <= NULL_BIAS_BPM,
        )
        report.evidence = {
            "chosen": {"trend_scale": best["trend_scale"], "event_scale": best["event_scale"], **chosen},
            "null_control": null,
            "rq3": {**rq3_summary, "power_runs": power_runs, "null_runs": null_runs},
            "grid": grid,
        }
    except Exception as failure:
        error = failure
    report.finish(error)
    out = report.write()
    if args.write and report.status == "passed" and choice is not None:
        write_config(choice[0], choice[1], choice[2], choice[3], choice[4], out)
    sys.stdout.write(f"calibration: {report.status} ({out.relative_to(ROOT)}/report.md)\n")
    return 0 if report.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
