select
    encounter_key,
    patient_key,
    provider_version_key,
    heart_rate_mean,
    heart_rate_min,
    heart_rate_max,
    heart_rate_stddev,
    respiratory_rate_mean,
    respiratory_rate_min,
    respiratory_rate_max,
    spo2_mean,
    spo2_min,
    systolic_bp_mean,
    systolic_bp_min,
    diastolic_bp_mean,
    label_definition_version,
    'vital-features-v2' as feature_schema_version
from {{ ref('fct_encounter_vital_features') }}
where is_scoring_eligible
