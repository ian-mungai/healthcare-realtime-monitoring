{#- NEWS2 (Royal College of Physicians 2017, SpO2 scale 1) at the end of each encounter's feature window, from the last
    value of each of its seven parameters; services/news2.py scores one observation set the same way. The total is
    missing when any parameter has no value in the window, so a missing parameter never scores as normal. -#}
with feature_observations as (
    select
        features.encounter_key,
        features.patient_key,
        features.feature_cutoff_at,
        facts.loinc_code,
        facts.value,
        row_number() over (
            partition by features.encounter_key, facts.loinc_code
            order by facts.effective_datetime desc, facts.fact_observation_key desc
        ) as recency
    from {{ ref('fact_encounter_vital_features') }} as features
    inner join {{ ref('fact_observations') }} as facts
        on features.encounter_key = facts.encounter_key
    where facts.effective_datetime < features.feature_cutoff_at
),

last_values as (
    select
        encounter_key,
        patient_key,
        feature_cutoff_at,
        max(case when loinc_code = '{{ var("vital_sign_loinc_codes")["respiratory_rate"] }}' then value end) as respiratory_rate,
        max(case when loinc_code = '{{ var("vital_sign_loinc_codes")["spo2"] }}' then value end) as spo2,
        max(case when loinc_code = '{{ var("vital_sign_loinc_codes")["inhaled_oxygen_concentration"] }}' then value end) as inhaled_oxygen_concentration,
        max(case when loinc_code = '{{ var("vital_sign_loinc_codes")["systolic_bp"] }}' then value end) as systolic_bp,
        max(case when loinc_code = '{{ var("vital_sign_loinc_codes")["heart_rate"] }}' then value end) as heart_rate,
        max(case when loinc_code = '{{ var("vital_sign_loinc_codes")["consciousness_level"] }}' then value end) as consciousness_level,
        max(case when loinc_code = '{{ var("vital_sign_loinc_codes")["temperature"] }}' then value end) as temperature
    from feature_observations
    where recency = 1
    group by
        encounter_key,
        patient_key,
        feature_cutoff_at
),

scores as (
    select
        *,
        case
            when respiratory_rate <= 8 then 3
            when respiratory_rate <= 11 then 1
            when respiratory_rate <= 20 then 0
            when respiratory_rate <= 24 then 2
            when respiratory_rate is not null then 3
        end as respiratory_rate_score,
        case
            when spo2 <= 91 then 3
            when spo2 <= 93 then 2
            when spo2 <= 95 then 1
            when spo2 is not null then 0
        end as spo2_score,
        case
            when inhaled_oxygen_concentration > 21 then 2
            when inhaled_oxygen_concentration is not null then 0
        end as inhaled_oxygen_score,
        case
            when systolic_bp <= 90 then 3
            when systolic_bp <= 100 then 2
            when systolic_bp <= 110 then 1
            when systolic_bp <= 219 then 0
            when systolic_bp is not null then 3
        end as systolic_bp_score,
        case
            when heart_rate <= 40 then 3
            when heart_rate <= 50 then 1
            when heart_rate <= 90 then 0
            when heart_rate <= 110 then 1
            when heart_rate <= 130 then 2
            when heart_rate is not null then 3
        end as heart_rate_score,
        case
            when consciousness_level = 0 then 0
            when consciousness_level is not null then 3
        end as consciousness_score,
        case
            when temperature <= 35.0 then 3
            when temperature <= 36.0 then 1
            when temperature <= 38.0 then 0
            when temperature <= 39.0 then 1
            when temperature is not null then 2
        end as temperature_score
    from last_values
)

select
    encounter_key,
    patient_key,
    feature_cutoff_at as scored_at,
    respiratory_rate,
    spo2,
    inhaled_oxygen_concentration,
    systolic_bp,
    heart_rate,
    consciousness_level,
    temperature,
    respiratory_rate_score,
    spo2_score,
    inhaled_oxygen_score,
    systolic_bp_score,
    heart_rate_score,
    consciousness_score,
    temperature_score,
    'news2-rcp-2017-spo2-scale-1' as news2_version,
    respiratory_rate_score + spo2_score + inhaled_oxygen_score + systolic_bp_score + heart_rate_score + consciousness_score + temperature_score
        as news2_total
from scores
