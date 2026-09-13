select
    model_version,
    encounter_key
from {{ ref('ml_predictions_serving') }}
where deterioration_probability < 0
    or deterioration_probability > 1
    or decision_threshold < 0
    or decision_threshold > 1
