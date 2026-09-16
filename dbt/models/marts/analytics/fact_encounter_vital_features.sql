with encounter_windows as (
    select
        encounter_key,
        patient_key,
        provider_key,
        provider_version_key,
        encounter_start_at,
        encounter_end_at,
        date_add(
            'minute',
            {{ var('feature_window_minutes') }},
            encounter_start_at
        ) as feature_cutoff_at,
        date_add(
            'minute',
            {{ var('feature_window_minutes') + var('outcome_window_minutes') }},
            encounter_start_at
        ) as outcome_cutoff_at
    from {{ ref('dim_encounter') }}
),

windowed_observations as (
    select
        encounters.*,
        facts.loinc_code,
        facts.value,
        facts.effective_datetime,
        facts.effective_datetime < encounters.feature_cutoff_at as is_feature_observation,
        facts.effective_datetime >= encounters.feature_cutoff_at
            and facts.effective_datetime < encounters.outcome_cutoff_at as is_outcome_observation
    from encounter_windows as encounters
    inner join {{ ref('fact_observations') }} as facts
        on encounters.encounter_key = facts.encounter_key
),

features_and_outcomes as (
    select
        encounter_key,
        patient_key,
        provider_key,
        provider_version_key,
        encounter_start_at,
        encounter_end_at,
        feature_cutoff_at,
        outcome_cutoff_at,
        date_diff('second', encounter_start_at, feature_cutoff_at) as feature_window_seconds,
        sum(case when is_feature_observation then 1 else 0 end) as feature_observation_count,
        sum(case when is_outcome_observation then 1 else 0 end) as outcome_observation_count,
        avg(case when is_feature_observation and loinc_code = '{{ var("vital_sign_loinc_codes")["heart_rate"] }}' then value end) as heart_rate_mean,
        min(case when is_feature_observation and loinc_code = '{{ var("vital_sign_loinc_codes")["heart_rate"] }}' then value end) as heart_rate_min,
        max(case when is_feature_observation and loinc_code = '{{ var("vital_sign_loinc_codes")["heart_rate"] }}' then value end) as heart_rate_max,
        stddev_samp(case when is_feature_observation and loinc_code = '{{ var("vital_sign_loinc_codes")["heart_rate"] }}' then value end) as heart_rate_stddev,
        avg(case when is_feature_observation and loinc_code = '{{ var("vital_sign_loinc_codes")["respiratory_rate"] }}' then value end) as respiratory_rate_mean,
        min(case when is_feature_observation and loinc_code = '{{ var("vital_sign_loinc_codes")["respiratory_rate"] }}' then value end) as respiratory_rate_min,
        max(case when is_feature_observation and loinc_code = '{{ var("vital_sign_loinc_codes")["respiratory_rate"] }}' then value end) as respiratory_rate_max,
        avg(case when is_feature_observation and loinc_code = '{{ var("vital_sign_loinc_codes")["spo2"] }}' then value end) as spo2_mean,
        min(case when is_feature_observation and loinc_code = '{{ var("vital_sign_loinc_codes")["spo2"] }}' then value end) as spo2_min,
        avg(case when is_feature_observation and loinc_code = '{{ var("vital_sign_loinc_codes")["systolic_bp"] }}' then value end) as systolic_bp_mean,
        min(case when is_feature_observation and loinc_code = '{{ var("vital_sign_loinc_codes")["systolic_bp"] }}' then value end) as systolic_bp_min,
        avg(case when is_feature_observation and loinc_code = '{{ var("vital_sign_loinc_codes")["diastolic_bp"] }}' then value end) as diastolic_bp_mean,
        sum(
            case
                when is_outcome_observation
                    and loinc_code = '{{ var("vital_sign_loinc_codes")["heart_rate"] }}'
                    and (value <= 40 or value >= 131)
                    then 1
                else 0
            end
        ) as outcome_heart_rate_extreme_count,
        sum(
            case
                when is_outcome_observation
                    and loinc_code = '{{ var("vital_sign_loinc_codes")["respiratory_rate"] }}'
                    and (value <= 8 or value >= 25)
                    then 1
                else 0
            end
        ) as outcome_respiratory_rate_extreme_count,
        sum(
            case
                when is_outcome_observation
                    and loinc_code = '{{ var("vital_sign_loinc_codes")["spo2"] }}'
                    and value <= 91
                    then 1
                else 0
            end
        ) as outcome_spo2_extreme_count,
        sum(
            case
                when is_outcome_observation
                    and loinc_code = '{{ var("vital_sign_loinc_codes")["systolic_bp"] }}'
                    and value <= 90
                    then 1
                else 0
            end
        ) as outcome_systolic_bp_extreme_count
    from windowed_observations
    group by
        encounter_key,
        patient_key,
        provider_key,
        provider_version_key,
        encounter_start_at,
        encounter_end_at,
        feature_cutoff_at,
        outcome_cutoff_at
),

features_and_labels as (
    select
        *,
        case
            when greatest(
                outcome_heart_rate_extreme_count,
                outcome_respiratory_rate_extreme_count,
                outcome_spo2_extreme_count,
                outcome_systolic_bp_extreme_count
            ) >= {{ var('deterioration_min_repeated_extreme_observations') }} then 1
            else 0
        end as deterioration_proxy_label
    from features_and_outcomes
)

select
    *,
    current_timestamp >= feature_cutoff_at and feature_observation_count > 0 as is_scoring_eligible,
    current_timestamp >= outcome_cutoff_at
        and feature_observation_count > 0
        and outcome_observation_count > 0 as is_training_eligible,
    'news2-repeated-extreme-proxy-v2' as label_definition_version
from features_and_labels
