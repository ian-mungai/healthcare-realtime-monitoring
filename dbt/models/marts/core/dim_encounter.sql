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
),

encounters as (
    select
        encounter_business_id,
        encounter_id,
        patient_id,
        min(effective_datetime) as encounter_start_at,
        max(effective_datetime) as encounter_end_at
    from normalized_encounters
    group by
        encounter_business_id,
        encounter_id,
        patient_id
),

numbered_encounters as (
    select
        *,
        row_number() over (order by encounter_business_id) as encounter_number
    from encounters
),

provider_roster as (
    select
        provider_npi,
        row_number() over (order by provider_npi) as provider_number,
        count(*) over () as provider_count
    from {{ ref('dim_provider') }}
    where is_current
),

assigned_encounters as (
    select
        encounters.*,
        providers.provider_npi
    from numbered_encounters as encounters
    inner join provider_roster as providers
        on providers.provider_number = mod(encounters.encounter_number - 1, providers.provider_count) + 1
)

select
    {{ stable_key("encounters.encounter_business_id") }} as encounter_key,
    encounters.encounter_id,
    case
        when encounters.encounter_id is null then cast(null as varchar)
        else concat('Encounter/', encounters.encounter_id)
    end as encounter_reference,
    {{ stable_key("encounters.patient_id") }} as patient_key,
    encounters.patient_id,
    providers.provider_key,
    providers.provider_version_key,
    encounters.encounter_start_at,
    encounters.encounter_end_at,
    encounters.encounter_id is null as is_legacy_unknown,
    true as is_synthetic_provider_assignment
from assigned_encounters as encounters
inner join {{ ref('dim_provider') }} as providers
    on encounters.provider_npi = providers.provider_npi
    and cast(encounters.encounter_start_at as date) >= providers.valid_from
    and cast(encounters.encounter_start_at as date) < coalesce(providers.valid_to, date '9999-12-31')
