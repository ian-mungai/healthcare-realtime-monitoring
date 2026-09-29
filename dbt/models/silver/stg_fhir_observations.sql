with source as (
    select *
    from {{ source('healthcare_realtime', 'processed_fhir_observations') }}
)

{% set active_patient_ids = env_var('ACTIVE_PATIENT_IDS').split(',') %}

select
    observation_id,
    patient_id,
    encounter_id,
    observation_type,
    loinc_code,
    value,
    unit,
    effective_datetime,
    received_at,
    source,
    year,
    month,
    day
from source
where encounter_id is not null
    and trim(encounter_id) <> ''
    and patient_id in (
        {% for patient_id in active_patient_ids %}
            '{{ patient_id | trim }}'{% if not loop.last %},{% endif %}
        {% endfor %}
    )
