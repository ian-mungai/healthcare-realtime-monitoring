{{ config(enabled=var('cohort_reference_enabled', false)) }}

{#- One row per unit and UTC hour that holds a simulated admission: the census (admissions present at any time in the
    hour), the admissions and discharges in it and the acuity of the patients present, as their admission NEWS2. -#}
with digits as (
    select digit
    from (values (0), (1), (2), (3), (4), (5), (6), (7), (8), (9)) as digit_values (digit)
),

hour_offsets as (
    select hundreds.digit * 100 + tens.digit * 10 + ones.digit as hour_offset
    from digits as hundreds
    cross join digits as tens
    cross join digits as ones
),

admissions as (
    select
        admissions.admission_key,
        admissions.unit_key,
        admissions.facility_key,
        admissions.unit,
        admissions.admitted_at,
        admissions.discharged_at,
        news2.news2_total,
        date_trunc('hour', admissions.admitted_at) as first_hour
    from {{ ref('fact_admissions') }} as admissions
    left join {{ ref('fact_encounter_news2') }} as news2
        on admissions.encounter_key = news2.encounter_key
),

present as (
    select
        admissions.*,
        {{ add_hours('hour_offsets.hour_offset', 'admissions.first_hour') }} as hour_start
    from admissions
    inner join hour_offsets
        on {{ add_hours('hour_offsets.hour_offset', 'admissions.first_hour') }} < admissions.discharged_at
)

select
    {{ stable_key("concat(unit_key, '|', cast(hour_start as varchar))") }} as unit_hour_key,
    unit_key,
    facility_key,
    unit,
    hour_start,
    {{ date_key('hour_start') }} as date_key,
    count(*) as census,
    sum(case when admitted_at >= hour_start and admitted_at < {{ add_hours('1', 'hour_start') }} then 1 else 0 end) as admissions,
    sum(case when discharged_at >= hour_start and discharged_at < {{ add_hours('1', 'hour_start') }} then 1 else 0 end) as discharges,
    avg(news2_total) as mean_admission_news2,
    sum(case when news2_total >= 5 then 1 else 0 end) as patients_news2_5_or_more,
    sum(case when news2_total >= 7 then 1 else 0 end) as patients_news2_7_or_more
from present
group by
    unit_key,
    facility_key,
    unit,
    hour_start
