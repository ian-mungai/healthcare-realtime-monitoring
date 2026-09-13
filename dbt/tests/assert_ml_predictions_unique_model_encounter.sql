select
    model_version,
    encounter_key,
    count(*) as duplicate_count
from {{ ref('ml_predictions_serving') }}
group by model_version, encounter_key
having count(*) > 1
