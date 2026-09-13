with encounter_windows as (
    select
        encounter_key,
        patient_key,
        provider_key,
        provider_version_key,
        encounter_start_at,
        encounter_end_at,
        date_add(
            'second',
            cast(floor(date_diff('second', encounter_start_at, encounter_end_at) * 0.8) as bigint),
            encounter_start_at
        ) as feature_cutoff_at
    from {{ ref('dim_encounter') }}
),

windowed_observations as (
    select
        encounters.*,
        facts.loinc_code,
        facts.value,
        facts.effective_datetime,
        facts.effective_datetime < encounters.feature_cutoff_at as is_feature_observation,
        facts.effective_datetime >= encounters.feature_cutoff_at as is_outcome_observation
    from encounter_windows as encounters
    inner join {{ ref('fact_observations') }} as facts
        on encounters.encounter_key = facts.encounter_key
),

features_and_labels as (
    select
        encounter_key,
        patient_key,
        provider_key,
        provider_version_key,
        encounter_start_at,
        encounter_end_at,
        feature_cutoff_at,
        date_diff('second', encounter_start_at, feature_cutoff_at) as feature_window_seconds,
        sum(case when is_feature_observation then 1 else 0 end) as feature_observation_count,
        sum(case when is_outcome_observation then 1 else 0 end) as outcome_observation_count,
        avg(case when is_feature_observation and loinc_code = '8867-4' then value end) as heart_rate_mean,
        min(case when is_feature_observation and loinc_code = '8867-4' then value end) as heart_rate_min,
        max(case when is_feature_observation and loinc_code = '8867-4' then value end) as heart_rate_max,
        stddev_samp(case when is_feature_observation and loinc_code = '8867-4' then value end) as heart_rate_stddev,
        avg(case when is_feature_observation and loinc_code = '9279-1' then value end) as respiratory_rate_mean,
        min(case when is_feature_observation and loinc_code = '9279-1' then value end) as respiratory_rate_min,
        max(case when is_feature_observation and loinc_code = '9279-1' then value end) as respiratory_rate_max,
        avg(case when is_feature_observation and loinc_code = '2708-6' then value end) as spo2_mean,
        min(case when is_feature_observation and loinc_code = '2708-6' then value end) as spo2_min,
        avg(case when is_feature_observation and loinc_code = '8480-6' then value end) as systolic_bp_mean,
        min(case when is_feature_observation and loinc_code = '8480-6' then value end) as systolic_bp_min,
        avg(case when is_feature_observation and loinc_code = '8462-4' then value end) as diastolic_bp_mean,
        max(
            case
                when not is_outcome_observation then 0
                when loinc_code = '8867-4' and (value <= 40 or value >= 131) then 1
                when loinc_code = '9279-1' and (value <= 8 or value >= 25) then 1
                when loinc_code = '2708-6' and value <= 91 then 1
                when loinc_code = '8480-6' and value <= 90 then 1
                else 0
            end
        ) as deterioration_proxy_label
    from windowed_observations
    group by
        encounter_key,
        patient_key,
        provider_key,
        provider_version_key,
        encounter_start_at,
        encounter_end_at,
        feature_cutoff_at
)

select
    *,
    feature_observation_count > 0 and outcome_observation_count > 0 as is_training_eligible,
    'news2-extreme-proxy-v1' as label_definition_version
from features_and_labels
