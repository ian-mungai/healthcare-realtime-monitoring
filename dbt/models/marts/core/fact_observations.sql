select
    observation_id,
    patient_id,
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
from {{ ref('stg_fhir_observations') }}