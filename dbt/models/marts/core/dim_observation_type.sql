select
    observation_type,
    loinc_code,
    unit,
    count(*) as observation_count,
    min(effective_datetime) as first_observation_at,
    max(effective_datetime) as latest_observation_at
from {{ ref('stg_fhir_observations') }}
group by
    observation_type,
    loinc_code,
    unit