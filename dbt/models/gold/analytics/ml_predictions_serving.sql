select
    model_version,
    encounter_key,
    patient_key,
    data_split,
    actual_label,
    deterioration_probability,
    predicted_label,
    decision_threshold,
    feature_schema_version,
    label_definition_version,
    dataset_fingerprint,
    scored_at
from {{ source('model_serving', 'ml_predictions_published') }}
