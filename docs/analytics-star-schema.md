# Analytics Star Schema

## Fact grain

`${ATHENA_DBT_DATABASE}.${DBT_FACT_OBSERVATIONS_TABLE}` contains one vital-sign measurement per `observation_id` and `loinc_code`. Blood pressure panels therefore produce separate systolic and diastolic fact rows while retaining the same FHIR observation identifier.

`fact_observation_key` is the stable hash of that compound business key. The fact also carries conformed foreign keys for patient, encounter, effective provider version, observation type, and observation date. Natural identifiers remain available for traceability and compatibility with existing validation queries.

## Conformed dimensions

| Dimension | Business key | Surrogate key | Purpose |
| --- | --- | --- | --- |
| `DBT_DIM_PATIENT_TABLE` | `patient_id` | `patient_key` | Synthetic FHIR subject identity and source classification |
| `DBT_DIM_ENCOUNTER_TABLE` | `encounter_id` | `encounter_key` | Patient encounter and its observed analysis window |
| `DBT_DIM_PROVIDER_TABLE` | `provider_npi` plus `valid_from` | `provider_version_key` | Effective-dated provider identity, taxonomy, and state |
| `DBT_DIM_OBSERVATION_TYPE_TABLE` | `loinc_code` | `observation_type_key` | LOINC vital-sign name, code, unit, and code system |
| `DBT_DIM_DATE_TABLE` | `full_date` | `date_key` | Calendar attributes for the observation date |

All hash keys use lowercase MD5 hex over stable UTF-8 business identifiers. `date_key` uses the integer `YYYYMMDD` convention.

Historical schema `1.0` events have no encounter identifier. They map to a deterministic patient-specific unknown encounter member so fact rows retain referential integrity without inventing a clinical encounter. New schema `1.1` events require `encounter_id`.

The table named by `DBT_DIM_PROVIDER_TABLE` uses a type 2 slowly changing dimension. A changed provider name, taxonomy, description, or state closes the current row at the new snapshot's effective date and creates a successor row. Encounter and fact rows retain both the stable `provider_key` and the effective `provider_version_key`.

The committed provider seed is a synthetic NPPES-compatible fixture for reproducible portfolio runs. Because the source observations do not contain a practitioner reference, the table named by `DBT_DIM_ENCOUNTER_TABLE` assigns the current synthetic roster deterministically and marks the result with `is_synthetic_provider_assignment`. This demonstrates temporal attribution mechanics; it does not claim that a named clinician treated a patient.

To prepare a private provider history from a normalized NPPES snapshot, supply `provider_npi`, `provider_name`, `taxonomy_code`, `taxonomy_description`, and `provider_state`:

```bash
python -m scripts.nppes.update_provider_history \
  --snapshot path/to/nppes_snapshot.csv \
  --history dbt/seeds/provider_history.csv \
  --output path/to/provider_history.csv \
  --effective-date YYYY-MM-DD
```

Review the generated history before replacing the synthetic seed. Do not commit real provider data to the portfolio repository.

## Bus matrix

| Business process | Grain | Patient | Encounter | Provider | Observation type | Date | Measures |
| --- | --- | :---: | :---: | :---: | :---: | :---: | --- |
| Record vital-sign observation | One row per observation ID and LOINC code | X | X | X | X | X | `value` |
| Construct encounter features and label | One row per encounter | X | X | X |  |  | Vital aggregates and deterioration proxy |

## Feature and label construction

`${ATHENA_DBT_DATABASE}.${DBT_ENCOUNTER_FEATURES_TABLE}` uses absolute windows that are independent of the encounter's eventual duration. The first 15 minutes produce model-ready vital aggregates and the following 15 minutes produce the binary `deterioration_proxy_label`. The tables named by `DBT_ML_SCORING_TABLE` and `DBT_ML_TRAINING_TABLE` become eligible after the feature and outcome windows respectively.

The versioned `news2-repeated-extreme-proxy-v2` label is `1` when at least two observations of the same vital cross a NEWS2 extreme threshold during the outcome window: heart rate at or below 40 or at or above 131, respiratory rate at or below 8 or at or above 25, oxygen saturation at or below 91, or systolic pressure at or below 90. Requiring repeated threshold crossings prevents one isolated synthetic measurement from determining the encounter label. The minimum count is declared by `deterioration_min_repeated_extreme_observations` in `dbt_project.yml`. `is_training_eligible` requires observations in both windows.

This label is a synthetic engineering proxy derived from NEWS2 extreme thresholds. It is not a diagnosis, a validated clinical outcome, or suitable for patient care or clinical model training.

## Training dataset

`${ATHENA_DBT_DATABASE}.${DBT_ML_TRAINING_TABLE}` contains only training-eligible encounters and preserves the feature and label definition versions. The split is deterministic: a stable bucket derived from `patient_key` assigns buckets 0 through 7 to training and 8 through 9 to testing. Grouping by patient prevents encounters for the same synthetic patient from appearing in both partitions.

The baseline model uses the twelve vital-sign aggregates as predictors. Encounter, patient, and provider keys remain available for traceability but are excluded from model features.

## Join paths

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

dbt tests enforce unique dimension keys, non-overlapping provider versions, one current provider row, the compound fact grain, every fact-to-dimension relationship, valid binary labels, and both label classes in each training split. Soda independently checks table population, missing keys, duplicate keys, and accepted label values.
