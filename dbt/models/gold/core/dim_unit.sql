{{ config(enabled=var('cohort_reference_enabled', false)) }}

{#- One row per facility and inpatient unit. Every simulated facility has each unit in the hospital_units seed. -#}
select
    {{ stable_key("concat(facilities.facility_id, '|', units.unit_name)") }} as unit_key,
    facilities.facility_key,
    facilities.facility_id,
    facilities.facility_name,
    units.unit_name,
    units.care_level,
    units.care_level_rank
from {{ ref('dim_facility') }} as facilities
cross join {{ ref('hospital_units') }} as units
