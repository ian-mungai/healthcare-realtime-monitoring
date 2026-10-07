{#- Patients that share a reused BIDMC waveform record share a split group, so they always land in the same split.
    Without the cohort reference tables, each patient is its own group. -#}
{% if var('cohort_reference_enabled', false) %}
    {%- set split_key = 'split_key' %}
    with grouped_features as (
        select
            features.*,
            coalesce({{ stable_key('groups.split_group') }}, features.patient_key) as split_key
        from {{ ref('fact_encounter_vital_features') }} as features
        left join {{ source('cohort_reference', 'patient_split_groups') }} as groups
            on features.patient_key = {{ stable_key('groups.patient_id') }}
    )

{% else %}
    {%- set split_key = 'patient_key' %}
{% endif %}
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
    'vital-features-v2' as feature_schema_version,
    mod({{ hex_prefix_number(split_key, 7) }}, 10) as split_bucket,
    case
        when mod({{ hex_prefix_number(split_key, 7) }}, 10) < 8 then 'train'
        else 'test'
    end as data_split
{% if var('cohort_reference_enabled', false) %}
    from grouped_features
{% else %}
    from {{ ref('fact_encounter_vital_features') }}
{% endif %}
where is_training_eligible
