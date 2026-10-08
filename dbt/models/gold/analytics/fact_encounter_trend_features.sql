{{ config(enabled=var('cohort_reference_enabled', false)) }}

{#- Per training encounter, the least-squares slope of each vital's feature-window minute means over the minute index:
    the change per minute that the planted early-warning trend adds. -#}
select
    encounter_key,
    patient_key,
    deterioration_proxy_label,
    regr_slope(
        cast(heart_rate_mean as {{ dbt.type_float() }}), cast(minute_index as {{ dbt.type_float() }})
        {{ in_row_order('minute_index') }}
    ) as heart_rate_slope,
    regr_slope(
        cast(respiratory_rate_mean as {{ dbt.type_float() }}), cast(minute_index as {{ dbt.type_float() }})
        {{ in_row_order('minute_index') }}
    ) as respiratory_rate_slope,
    regr_slope(
        cast(spo2_mean as {{ dbt.type_float() }}), cast(minute_index as {{ dbt.type_float() }})
        {{ in_row_order('minute_index') }}
    ) as spo2_slope,
    regr_slope(
        cast(systolic_bp_mean as {{ dbt.type_float() }}), cast(minute_index as {{ dbt.type_float() }})
        {{ in_row_order('minute_index') }}
    ) as systolic_bp_slope,
    regr_slope(
        cast(temperature_mean as {{ dbt.type_float() }}), cast(minute_index as {{ dbt.type_float() }})
        {{ in_row_order('minute_index') }}
    ) as temperature_slope
from {{ ref('fact_encounter_minute_features') }}
group by
    encounter_key,
    patient_key,
    deterioration_proxy_label
