{{ config(enabled=var('cohort_reference_enabled', false)) }}

{#- Type 2 patient dimension: one row per patient and payer period, with the patient's Synthea demographics. -#}
with payer_periods as (
    select
        patient_id,
        payer_name,
        cast(valid_from as date) as valid_from,
        cast(valid_to as date) as valid_to
    from {{ source('cohort_reference', 'patient_payer_history') }}
),

patients as (
    select
        patient_id,
        gender,
        race,
        ethnicity,
        marital_status,
        state,
        cast(birth_date as date) as birth_date
    from {{ source('cohort_reference', 'fhir_patients') }}
)

select
    {{ stable_key("concat(periods.patient_id, '|', cast(periods.valid_from as varchar))") }} as patient_version_key,
    {{ stable_key("periods.patient_id") }} as patient_key,
    periods.patient_id,
    patients.birth_date,
    patients.gender,
    patients.race,
    patients.ethnicity,
    patients.marital_status,
    patients.state,
    periods.payer_name,
    periods.valid_from,
    periods.valid_to,
    (periods.valid_to is null) as is_current
from payer_periods as periods
inner join patients
    on periods.patient_id = patients.patient_id
