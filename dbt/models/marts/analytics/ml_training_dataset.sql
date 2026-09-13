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
    deterioration_proxy_label,
    label_definition_version,
    'vital-features-v1' as feature_schema_version,
    mod(from_base(substr(patient_key, 1, 7), 16), 10) as split_bucket,
    case
        when mod(from_base(substr(patient_key, 1, 7), 16), 10) < 8 then 'train'
        else 'test'
    end as data_split
from {{ ref('fct_encounter_vital_features') }}
where is_training_eligible
