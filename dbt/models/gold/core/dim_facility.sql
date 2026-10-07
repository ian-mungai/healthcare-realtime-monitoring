{{ config(enabled=var('cohort_reference_enabled', false)) }}

select
    {{ stable_key("facility_id") }} as facility_key,
    facility_id,
    facility_name,
    city,
    state
from {{ source('cohort_reference', 'facilities') }}
