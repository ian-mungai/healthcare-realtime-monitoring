{{ config(enabled=var('cohort_reference_enabled', false)) }}

{#- One row per simulated admission, at the patient version valid on the admission date. -#}
with admissions as (
    select
        encounter_id,
        patient_id,
        run_id,
        scenario,
        facility_id,
        unit,
        diagnosis_code,
        diagnosis_display,
        diagnosis_source,
        cast(admitted_at as timestamp) as admitted_at,
        cast(discharged_at as timestamp) as discharged_at
    from {{ source('cohort_reference', 'admissions') }}
)

select
    {{ stable_key("admissions.encounter_id") }} as admission_key,
    {{ stable_key("admissions.encounter_id") }} as encounter_key,
    {{ stable_key("admissions.patient_id") }} as patient_key,
    versions.patient_version_key,
    {{ stable_key("admissions.facility_id") }} as facility_key,
    {{ stable_key("concat(admissions.facility_id, '|', admissions.unit)") }} as unit_key,
    {{ date_key('admissions.admitted_at') }} as admit_date_key,
    admissions.encounter_id,
    admissions.run_id,
    admissions.scenario,
    admissions.admitted_at,
    admissions.discharged_at,
    {{ seconds_between('admissions.admitted_at', 'admissions.discharged_at') }} / 3600 as length_of_stay_hours,
    admissions.unit,
    admissions.diagnosis_code,
    admissions.diagnosis_display,
    admissions.diagnosis_source,
    versions.birth_date,
    {{ seconds_between('versions.birth_date', 'admissions.admitted_at') }} / 31557600 as age_at_admission_years
from admissions
left join {{ ref('dim_patient_version') }} as versions
    on
        admissions.patient_id = versions.patient_id
        and cast(admissions.admitted_at as date) >= versions.valid_from
        and (versions.valid_to is null or cast(admissions.admitted_at as date) < versions.valid_to)
