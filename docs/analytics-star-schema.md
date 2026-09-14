# Analytics Star Schema

## Fact grain

`healthcare_realtime_dbt.fact_observations` contains one vital-sign measurement per `observation_id` and `loinc_code`. Blood pressure panels therefore produce separate systolic and diastolic fact rows while retaining the same FHIR observation identifier.

`fact_observation_key` is the stable hash of that compound business key. The fact also carries conformed foreign keys for patient, encounter, effective provider version, observation type, and observation date. Natural identifiers remain available for traceability and compatibility with existing validation queries.

## Conformed dimensions

| Dimension | Business key | Surrogate key | Purpose |
| --- | --- | --- | --- |
| `dim_patient` | `patient_id` | `patient_key` | Synthetic FHIR subject identity and source classification |
| `dim_encounter` | `encounter_id` | `encounter_key` | Patient encounter and its observed analysis window |
| `dim_provider` | `provider_npi` plus `valid_from` | `provider_version_key` | Effective-dated provider identity, taxonomy, and state |
| `dim_observation_type` | `loinc_code` | `observation_type_key` | LOINC vital-sign name, code, unit, and code system |
| `dim_date` | `full_date` | `date_key` | Calendar attributes for the observation date |

All hash keys use lowercase MD5 hex over stable UTF-8 business identifiers. `date_key` uses the integer `YYYYMMDD` convention.

Historical schema `1.0` events have no encounter identifier. They map to a deterministic patient-specific unknown encounter member so fact rows retain referential integrity without inventing a clinical encounter. New schema `1.1` events require `encounter_id`.

`dim_provider` uses a type 2 slowly changing dimension. A changed provider name, taxonomy, description, or state closes the current row at the new snapshot's effective date and creates a successor row. Encounter and fact rows retain both the stable `provider_key` and the effective `provider_version_key`.

The committed provider seed is a synthetic NPPES-compatible fixture for reproducible portfolio runs. Because the source observations do not contain a practitioner reference, `dim_encounter` assigns the current synthetic roster deterministically and marks the result with `is_synthetic_provider_assignment`. This demonstrates temporal attribution mechanics; it does not claim that a named clinician treated a patient.

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

`healthcare_realtime_dbt.fct_encounter_vital_features` uses absolute windows that are independent of the encounter's eventual duration. The first 15 minutes produce model-ready vital aggregates and the following 15 minutes produce the binary `deterioration_proxy_label`. `ml_scoring_dataset` becomes eligible after the feature window; `ml_training_dataset` additionally requires observations in the outcome window.

The versioned `news2-extreme-proxy-v1` label is `1` when the outcome window contains heart rate at or below 40 or at or above 131, respiratory rate at or below 8 or at or above 25, oxygen saturation at or below 91, or systolic pressure at or below 90. `is_training_eligible` requires observations in both windows.

This label is a synthetic engineering proxy derived from NEWS2 extreme thresholds. It is not a diagnosis, a validated clinical outcome, or suitable for patient care or clinical model training.

## Training dataset

`healthcare_realtime_dbt.ml_training_dataset` contains only training-eligible encounters and preserves the feature and label definition versions. The split is deterministic: a stable bucket derived from `patient_key` assigns buckets 0 through 7 to training and 8 through 9 to testing. Grouping by patient prevents encounters for the same synthetic patient from appearing in both partitions.

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
from healthcare_realtime_dbt.fact_observations as f
join healthcare_realtime_dbt.dim_patient as p
    on f.patient_key = p.patient_key
join healthcare_realtime_dbt.dim_encounter as e
    on f.encounter_key = e.encounter_key
join healthcare_realtime_dbt.dim_provider as pr
    on f.provider_version_key = pr.provider_version_key
join healthcare_realtime_dbt.dim_observation_type as o
    on f.observation_type_key = o.observation_type_key
join healthcare_realtime_dbt.dim_date as d
    on f.date_key = d.date_key
```

dbt tests enforce unique dimension keys, non-overlapping provider versions, one current provider row, the compound fact grain, every fact-to-dimension relationship, and valid binary labels. Soda independently checks table population, missing keys, duplicate keys, and accepted label values.
