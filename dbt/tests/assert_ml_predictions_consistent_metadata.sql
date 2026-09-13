select model_version
from {{ ref('ml_predictions_serving') }}
group by model_version
having count(distinct decision_threshold) <> 1
    or count(distinct feature_schema_version) <> 1
    or count(distinct label_definition_version) <> 1
    or count(distinct dataset_fingerprint) <> 1
    or count(distinct scored_at) <> 1
