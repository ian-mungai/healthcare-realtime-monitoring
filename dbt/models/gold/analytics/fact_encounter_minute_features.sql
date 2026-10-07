{{ config(enabled=var('cohort_reference_enabled', false)) }}

{#- One row per encounter and minute of the feature window: the repeated measures for the GEE model. -#}
with feature_observations as (
    select
        features.encounter_key,
        features.patient_key,
        features.deterioration_proxy_label,
        facts.loinc_code,
        facts.value,
        cast(floor({{ seconds_between('features.encounter_start_at', 'facts.effective_datetime') }} / 60) as integer) as minute_index
    from {{ ref('fact_encounter_vital_features') }} as features
    inner join {{ ref('fact_observations') }} as facts
        on features.encounter_key = facts.encounter_key
    where
        features.is_training_eligible
        and facts.effective_datetime < features.feature_cutoff_at
)

select
    {{ stable_key("concat(encounter_key, '|', cast(minute_index as varchar))") }} as encounter_minute_key,
    encounter_key,
    patient_key,
    minute_index,
    deterioration_proxy_label,
    count(*) as observation_count,
    avg(case when loinc_code = '{{ var("vital_sign_loinc_codes")["heart_rate"] }}' then value end) as heart_rate_mean,
    avg(case when loinc_code = '{{ var("vital_sign_loinc_codes")["respiratory_rate"] }}' then value end) as respiratory_rate_mean,
    avg(case when loinc_code = '{{ var("vital_sign_loinc_codes")["spo2"] }}' then value end) as spo2_mean,
    avg(case when loinc_code = '{{ var("vital_sign_loinc_codes")["systolic_bp"] }}' then value end) as systolic_bp_mean,
    avg(case when loinc_code = '{{ var("vital_sign_loinc_codes")["diastolic_bp"] }}' then value end) as diastolic_bp_mean
from feature_observations
group by
    encounter_key,
    patient_key,
    minute_index,
    deterioration_proxy_label
