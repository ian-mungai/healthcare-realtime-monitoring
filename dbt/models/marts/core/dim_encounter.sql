with normalized_encounters as (
    select
        coalesce(
            nullif(trim(encounter_id), ''),
            concat('__legacy_unknown__|', patient_id)
        ) as encounter_business_id,
        nullif(trim(encounter_id), '') as encounter_id,
        patient_id,
        effective_datetime
    from {{ ref('stg_fhir_observations') }}
    where patient_id is not null
)

select
    {{ stable_key("encounter_business_id") }} as encounter_key,
    encounter_id,
    case
        when encounter_id is null then cast(null as varchar)
        else concat('Encounter/', encounter_id)
    end as encounter_reference,
    {{ stable_key("patient_id") }} as patient_key,
    patient_id,
    min(effective_datetime) as encounter_start_at,
    max(effective_datetime) as encounter_end_at,
    encounter_id is null as is_legacy_unknown
from normalized_encounters
group by
    encounter_business_id,
    encounter_id,
    patient_id
