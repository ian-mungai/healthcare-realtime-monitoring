{{ config(materialized='view') }}

select
    predictions.model_version,
    predictions.encounter_key,
    predictions.patient_key,
    predictions.data_split,
    predictions.actual_label,
    predictions.deterioration_probability,
    predictions.predicted_label,
    predictions.decision_threshold,
    predictions.feature_schema_version,
    predictions.label_definition_version,
    predictions.dataset_fingerprint,
    predictions.scored_at,
    case
        when predicted_label = 1 then 'elevated_proxy'
        else 'baseline_proxy'
    end as proxy_risk_band,
    'synthetic_portfolio_only' as prediction_scope,
    false as is_clinically_validated
from {{ ref('ml_predictions_serving') }} as predictions
where predictions.model_version = '{{ env_var("ML_APPROVED_MODEL_VERSION") }}'
