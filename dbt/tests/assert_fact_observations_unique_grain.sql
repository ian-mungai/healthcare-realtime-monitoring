select
    observation_id,
    loinc_code,
    count(*) as duplicate_count
from {{ ref('fact_observations') }}
group by observation_id, loinc_code
having count(*) > 1
