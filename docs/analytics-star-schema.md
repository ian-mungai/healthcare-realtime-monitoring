# Analytics Star Schema

## Fact grain

`healthcare_realtime_dbt.fact_observations` contains one vital-sign measurement per `observation_id` and `loinc_code`. Blood pressure panels therefore produce separate systolic and diastolic fact rows while retaining the same FHIR observation identifier.

`fact_observation_key` is the stable hash of that compound business key. The fact also carries conformed foreign keys for patient, encounter, observation type, and observation date. Natural identifiers remain available for traceability and compatibility with existing validation queries.

## Conformed dimensions

| Dimension | Business key | Surrogate key | Purpose |
| --- | --- | --- | --- |
| `dim_patient` | `patient_id` | `patient_key` | Synthetic FHIR subject identity and source classification |
| `dim_encounter` | `encounter_id` | `encounter_key` | Patient encounter and its observed analysis window |
| `dim_observation_type` | `loinc_code` | `observation_type_key` | LOINC vital-sign name, code, unit, and code system |
| `dim_date` | `full_date` | `date_key` | Calendar attributes for the observation date |

All hash keys use lowercase MD5 hex over stable UTF-8 business identifiers. `date_key` uses the integer `YYYYMMDD` convention.

Historical schema `1.0` events have no encounter identifier. They map to a deterministic patient-specific unknown encounter member so fact rows retain referential integrity without inventing a clinical encounter. New schema `1.1` events require `encounter_id`.

## Bus matrix

| Business process | Grain | Patient | Encounter | Observation type | Date | Measures |
| --- | --- | :---: | :---: | :---: | :---: | --- |
| Record vital-sign observation | One row per observation ID and LOINC code | X | X | X | X | `value` |

## Join paths

```sql
select
    f.observation_id,
    p.patient_reference,
    e.encounter_reference,
    o.observation_type,
    d.full_date,
    f.value,
    o.unit
from healthcare_realtime_dbt.fact_observations as f
join healthcare_realtime_dbt.dim_patient as p
    on f.patient_key = p.patient_key
join healthcare_realtime_dbt.dim_encounter as e
    on f.encounter_key = e.encounter_key
join healthcare_realtime_dbt.dim_observation_type as o
    on f.observation_type_key = o.observation_type_key
join healthcare_realtime_dbt.dim_date as d
    on f.date_key = d.date_key
```

dbt tests enforce unique dimension keys, the compound fact grain, and every fact-to-dimension relationship. Soda independently checks table population, missing keys, duplicate keys, and the existing compound grain.
