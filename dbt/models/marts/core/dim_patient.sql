select
    patient_id,
    min(effective_datetime) as first_observation_at,
    max(effective_datetime) as latest_observation_at,
    count(*) as observation_row_count,
    count(distinct observation_id) as observation_count
from {{ ref('stg_fhir_observations') }}
group by patient_id