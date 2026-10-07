---
title: "Analytics Star Schema"
description: "Look up analytical grains, keys, conformed dimensions and permitted joins."
last_updated: 2026-10-07
audience: [developer, operator]
---

# Analytics Star Schema

For developers and operators: look up analytical grains, keys, conformed dimensions and permitted joins.

## Contents

- [Terminology](#terminology)
- [Model Layers](#model-layers)
- [Fact Grain](#fact-grain)
- [Conformed Dimensions](#conformed-dimensions)
- [Example Placeholders](#example-placeholders)
- [Prepare Private Provider History](#prepare-private-provider-history)
- [Bus Matrix](#bus-matrix)
- [Feature and Label Construction](#feature-and-label-construction)
- [Training Dataset](#training-dataset)
- [Join Paths](#join-paths)

## Terminology

- **BIDMC**: Beth Israel Deaconess Medical Center.
- **CSV**: comma-separated values.
- **FHIR**: Fast Healthcare Interoperability Resources.
- **ID**: identifier.
- **LOINC**: Logical Observation Identifiers Names and Codes.
- **MD5**: Message Digest 5.
- **NEWS2**: National Early Warning Score 2.
- **NPPES**: National Plan and Provider Enumeration System.
- **SNOMED CT**: Systematized Nomenclature of Medicine Clinical Terms.
- **SQL**: Structured Query Language.
- **UTF**: Unicode Transformation Format.

## Model Layers

The analytical path uses bronze, silver and gold layers. All dbt models build into the one dbt database, `${ATHENA_DBT_DATABASE}`.

| Layer | Location | Contents |
| --- | --- | --- |
| Bronze | S3 raw landing and the dbt sources in `dbt/models/sources.yml` | Landed Fast Healthcare Interoperability Resources (FHIR) vital events, the Glue-processed Iceberg observation table and the published model predictions |
| Silver | `dbt/models/silver/` | `stg_fhir_observations`, the cleaned and cohort-limited observations (view) |
| Gold | `dbt/models/gold/core/` and `dbt/models/gold/analytics/` | The star schema (`dim_` and `fact_` tables) and the feature, training, scoring and prediction datasets |

## Fact Grain

`${ATHENA_DBT_DATABASE}.${DBT_FACT_OBSERVATIONS_TABLE}` contains one vital-sign measurement per `observation_id` and `loinc_code`. Blood pressure panels therefore produce separate systolic and diastolic fact rows while retaining the same FHIR observation identifier.

`fact_observation_key` is the stable hash of that compound business key. The fact also carries conformed foreign keys for patient, encounter, effective provider version, observation type and observation date. Natural identifiers remain available for traceability and compatibility with existing validation queries.

## Conformed Dimensions

| Dimension | Business key | Surrogate key | Purpose |
| --- | --- | --- | --- |
| `DBT_DIM_PATIENT_TABLE` | `patient_id` | `patient_key` | Synthetic FHIR subject identity and source classification |
| `DBT_DIM_ENCOUNTER_TABLE` | `encounter_id` | `encounter_key` | Patient encounter and its observed analysis window |
| `DBT_DIM_PROVIDER_TABLE` | `provider_npi` plus `valid_from` | `provider_version_key` | Effective-dated provider identity, taxonomy and state |
| `DBT_DIM_OBSERVATION_TYPE_TABLE` | `loinc_code` | `observation_type_key` | Logical Observation Identifiers Names and Codes (LOINC) vital-sign name, code, unit and code system |
| `DBT_DIM_DATE_TABLE` | `full_date` | `date_key` | Calendar attributes for the observation date |

All hash keys use lowercase Message Digest 5 (MD5) hex over stable Unicode Transformation Format (UTF)-8 business identifiers. `date_key` uses the integer `YYYYMMDD` convention.

The analytical staging boundary includes only the ten patient identifiers supplied through the private deployment configuration and observations with a valid `encounter_id`. Historical schema `1.0` rows and out-of-cohort patients remain in the immutable source layer for audit and replay purposes but are excluded from the star schema. Schema `1.1` events require `encounter_id`.

The table named by `DBT_DIM_PROVIDER_TABLE` uses a type 2 slowly changing dimension. A changed provider name, taxonomy, description or state closes the current row at the new snapshot's effective date and creates a successor row. Encounter and fact rows retain both the stable `provider_key` and the effective `provider_version_key`.

### Cohort Reference Models

With the dbt variable `cohort_reference_enabled` set to true, dbt also builds models from the cohort reference tables (`dbt/models/sources.yml`, source `cohort_reference`). The local warehouse turns it on (Local Stack). The daily AWS workflow also turns it on after its `extract_cohort_reference` task refreshes the tables ([FHIR Setup Tasks](fhir-setup-tasks.md#how-it-runs)). The `parse_timestamp` macro reads the extract's ISO-8601 timestamps on both Athena and Postgres. The existing models compile to the same Athena SQL.

| Model | Business key | Surrogate key | Purpose |
| --- | --- | --- | --- |
| `dim_patient_version` | `patient_id` plus `valid_from` | `patient_version_key` | Synthea demographics and insurance payer as a type 2 slowly changing dimension: a payer change starts a new version |
| `dim_facility` | `facility_id` | `facility_key` | Synthea hospital name, city and state |
| `dim_unit` | `facility_id` plus `unit_name` | `unit_key` | Each facility's inpatient units with their care level (`critical`, `intermediate` or `acute`) from the `hospital_units` seed |
| `fact_admissions` | `encounter_id` | `admission_key` | One synthetic admission per encounter: facility, unit, admit and discharge times, length of stay, the SNOMED CT admitting diagnosis with its source (`synthea_history` or `simulator_fallback`), the `unit_key` of the admitting unit, the patient version valid on the admission date, age at admission and the attending provider's NPI, specialty and `provider_version_key` valid on the admission date |
| `fact_encounter_minute_features` | `encounter_key` plus `minute_index` | `encounter_minute_key` | Mean vitals for each of the 15 feature-window minutes of each training encounter |

The existing `DBT_DIM_PATIENT_TABLE` keeps its grain and columns. `fact_admissions` shares `encounter_key` and `patient_key` with the other facts.

The committed provider seed is a synthetic National Plan and Provider Enumeration System (NPPES)-compatible fixture for reproducible portfolio runs. [`scripts/nppes/provider_roster.py`](../scripts/nppes/provider_roster.py) builds it from [`config/provider_roster.json`](../config/provider_roster.json): 24 Washington inpatient physicians in eight NUCC taxonomy specialties (code set 26.1), with production-format NPIs (10 digits, leading 1, valid check digit) and realistic names. Two specialty changes and two moves between states give the type 2 history real versions. `--check-nppes` asks the NPPES NPI Registry once whether any NPI belongs to a real clinician anywhere in the US or any name to a real Washington clinician; a match moves that provider to its next seeded candidate. The config records only the attempt numbers and the check's counts, never a real clinician's details. Without the flag the script rebuilds the same seed offline.

Each simulated admission records its attending provider by NPI (`Encounter.participant`, type `ATND`). The simulator picks one, seeded by run and patient, among the providers whose version on the admission date practises in Washington and whose specialty covers the unit: critical care or pulmonary disease in the intensive care unit; cardiology, pulmonary disease or hospitalist on the step-down unit; and hospitalist, internal medicine, infectious disease, nephrology or surgery on the medical-surgical ward. The choice does not depend on the outcome scenario, so specialty is a negative control for the subgroup analysis. With the cohort reference tables, the table named by `DBT_DIM_ENCOUNTER_TABLE` takes the provider from the admission and sets `is_synthetic_provider_assignment` to false. Encounters without an admission keep the deterministic round-robin over the current roster, flagged true. So does every encounter when the reference tables are off. Either way this demonstrates temporal attribution mechanics; it does not claim that a named clinician treated a patient.

## Example Placeholders

- `<NPPES_SNAPSHOT>`: private normalized NPPES input CSV path.
- `<PROVIDER_HISTORY_OUTPUT>`: private generated provider-history CSV path.
- `<EFFECTIVE_DATE>`: approved snapshot date in `YYYY-MM-DD` format.

## Prepare Private Provider History

Prerequisites:

- A private normalized NPPES snapshot with `provider_npi`, `provider_name`, `taxonomy_code`, `taxonomy_description` and `provider_state`.
- The project virtual environment and an approved effective date.
- A private output path outside tracked files. Real provider data must remain outside this portfolio repository.

1. Generate the candidate history:

   ```bash
   .venv/bin/python -m scripts.nppes.update_provider_history \
     --snapshot "<NPPES_SNAPSHOT>" \
     --history dbt/seeds/provider_history.csv \
     --output "<PROVIDER_HISTORY_OUTPUT>" \
     --effective-date "<EFFECTIVE_DATE>"
   ```

2. Review the generated history before replacing any synthetic seed. Verify the effective date, changed attributes, closed predecessor rows and current successor rows.
3. Confirm the command completed without validation errors and the reviewed output remains private. A successful generation does not authorize committing real provider data.

## Bus Matrix

| Business process | Grain | Patient | Encounter | Provider | Observation type | Date | Measures |
| --- | --- | :---: | :---: | :---: | :---: | :---: | --- |
| Record vital-sign observation | One row per observation identifier (ID) and LOINC code | X | X | X | X | X | `value` |
| Construct encounter features and label | One row per encounter | X | X | X | | | Vital aggregates and deterioration proxy |
| Admit patient (reference models) | One row per admission | X | X | | | X | Length of stay, age at admission |
| Construct minute features (reference models) | One row per encounter and feature-window minute | X | X | | | | Per-minute vital means |

## Feature and Label Construction

`${ATHENA_DBT_DATABASE}.${DBT_ENCOUNTER_FEATURES_TABLE}` uses absolute windows that are independent of the encounter's eventual duration. The first 15 minutes produce model-ready vital aggregates and the following 15 minutes produce the binary `deterioration_proxy_label`. The tables named by `DBT_ML_SCORING_TABLE` and `DBT_ML_TRAINING_TABLE` become eligible after the feature and outcome windows respectively.

The versioned `news2-repeated-extreme-proxy-v2` label is `1` when at least two observations of the same vital cross a National Early Warning Score 2 (NEWS2) extreme threshold during the outcome window: heart rate at or below 40 or at or above 131, respiratory rate at or below 8 or at or above 25, oxygen saturation at or below 91 or systolic pressure at or below 90. Requiring repeated threshold crossings prevents one isolated synthetic measurement from determining the encounter label. The minimum count is declared by `deterioration_min_repeated_extreme_observations` in `dbt_project.yml`. `is_training_eligible` requires observations in both windows.

Every simulator task creates a new encounter for each cohort patient. For a run planned to cover the full 30-minute feature and outcome window, the [cohort runner](../services/vitals_simulator/app/simulation/realtime_cohort_runner.py) counts each patient's scenario-tagged encounters in HAPI FHIR. The [scenario selector](../services/vitals_simulator/app/simulation/scenario.py) chooses the less frequent normal or deterioration-proxy scenario. Ties use a stable hash of `SIMULATOR_SCENARIO_SEED` and the patient identifier when a seed is supplied or a random choice otherwise. Shorter planned runs use that seed or random choice without counting or tagging scenario history.

Planned duration uses the cycle cap and interval, limited by available source cycles when replay is disabled. An unset or blank `SIMULATOR_MAX_CYCLES` defaults to ten cycles in the runner; `none` or `unlimited` removes the cap. Terraform configures unlimited cycles with replay. Scenario tags are written at encounter creation, so interrupted or concurrent runs can affect the counts without producing eligible analytical rows. Two complete runs are an initial attempt to supply both classes, not a guarantee. Verify actual observations in both windows, class diversity in both patient-grouped partitions and no patient leakage before training.

Source Beth Israel Deaconess Medical Center (BIDMC) measurements and Synthea blood-pressure readings remain unchanged during the feature window of normal encounters. In deterioration encounters, the planted precursor of the simulation study ([`config/planted_signal.json`](../config/planted_signal.json)) adds a known early-warning trend to the feature window; that trend is the signal models are scored against. The fixed outcome-window values still define the label and the precursor never reaches the outcome window. The null control plants nothing, so its features carry no information about the label.

<details>
<summary>Old Patterns</summary>

At `5765c1e`, scenario selection used only random choice or the stable seed and patient identifier for every run. Reusing the same seed repeated the assignment rather than increasing scenario diversity. Neither one run nor repeated same-seed runs guaranteed both classes in either patient-grouped partition. The history-based selector replaces that assignment rule; the analytical class and leakage gates remain.

</details>

This label is a synthetic engineering proxy derived from NEWS2 extreme thresholds. It is not a diagnosis, a validated clinical outcome or suitable for patient care or clinical model training.

## Training Dataset

`${ATHENA_DBT_DATABASE}.${DBT_ML_TRAINING_TABLE}` contains only training-eligible encounters and preserves the feature and label definition versions. The split is deterministic: a stable bucket derived from `patient_key` assigns buckets 0 through 7 to training and 8 through 9 to testing. Grouping by patient prevents encounters for the same synthetic patient from appearing in both partitions. With the cohort reference models on, the bucket comes from the patient's waveform split group instead, so the two patients who share a reused BIDMC record also stay in one partition. A dbt test checks that no split group appears in both.

The baseline model uses the twelve vital-sign aggregates as predictors. `vital-features-v3` adds four bedside aggregates (temperature mean and maximum, maximum inhaled oxygen concentration and maximum consciousness ordinal), which the baseline does not use yet. Encounter, patient and provider keys remain available for traceability but are excluded from model features.

## Join Paths

This SQL is a template for Athena, not a directly runnable statement. Substitute the `${...}` identifiers with the corresponding database/table values in generated `infra/deployment.auto.tfvars.json`, using the mappings in `scripts/infrastructure/render_project_config.py`. Preserve identifier validation and use only the selected environment's catalog. The aliases and keys match the dbt dimension and fact models. Parsing after placeholder substitution checks syntax; execution needs an authorized deployed catalog.

```sql
select
    f.observation_id,
    p.patient_reference,
    e.encounter_reference,
    pr.provider_name,
    o.observation_type,
    d.full_date,
    f.value,
    o.unit
from ${ATHENA_DBT_DATABASE}.${DBT_FACT_OBSERVATIONS_TABLE} as f
join ${ATHENA_DBT_DATABASE}.${DBT_DIM_PATIENT_TABLE} as p
    on f.patient_key = p.patient_key
join ${ATHENA_DBT_DATABASE}.${DBT_DIM_ENCOUNTER_TABLE} as e
    on f.encounter_key = e.encounter_key
join ${ATHENA_DBT_DATABASE}.${DBT_DIM_PROVIDER_TABLE} as pr
    on f.provider_version_key = pr.provider_version_key
join ${ATHENA_DBT_DATABASE}.${DBT_DIM_OBSERVATION_TYPE_TABLE} as o
    on f.observation_type_key = o.observation_type_key
join ${ATHENA_DBT_DATABASE}.${DBT_DIM_DATE_TABLE} as d
    on f.date_key = d.date_key
```

dbt tests enforce unique dimension keys, non-overlapping provider versions, one current provider row, the compound fact grain, every fact-to-dimension relationship and valid binary labels. The class-readiness test warns when either training split lacks both classes. The training command keeps that condition as a hard failure so an invalid model cannot be produced. Soda independently checks table population, missing keys, duplicate keys and accepted label values.
