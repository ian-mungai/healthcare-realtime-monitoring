with normalized_encounters as (
    select
        patient_id,
        effective_datetime,
        trim(encounter_id) as encounter_business_id,
        trim(encounter_id) as encounter_id
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

{# A simulated admission records its attending; other encounters get a round-robin placeholder from the roster. #}
attendings as (
    {% if var('cohort_reference_enabled', false) -%}
        select
            encounter_id,
            attending_npi
        from {{ source('cohort_reference', 'admissions') }}
    {%- else -%}
        select
            cast(null as varchar) as encounter_id,
            cast(null as varchar) as attending_npi
        from (values (1)) as no_admissions (placeholder)
        where placeholder = 0
    {%- endif %}
),

assigned_encounters as (
    select
        encounters.*,
        coalesce(attendings.attending_npi, providers.provider_npi) as provider_npi,
        attendings.attending_npi is null as is_synthetic_provider_assignment
    from numbered_encounters as encounters
    inner join provider_roster as providers
        on providers.provider_number = mod(encounters.encounter_number - 1, providers.provider_count) + 1
    left join attendings
        on encounters.encounter_id = attendings.encounter_id
)

select
    {{ stable_key("encounters.encounter_business_id") }} as encounter_key,
    encounters.encounter_id,
    concat('Encounter/', encounters.encounter_id) as encounter_reference,
    {{ stable_key("encounters.patient_id") }} as patient_key,
    encounters.patient_id,
    providers.provider_key,
    providers.provider_version_key,
    encounters.encounter_start_at,
    encounters.encounter_end_at,
    encounters.is_synthetic_provider_assignment
from assigned_encounters as encounters
inner join {{ ref('dim_provider') }} as providers
    on
        encounters.provider_npi = providers.provider_npi
        and cast(encounters.encounter_start_at as date) >= providers.valid_from
        and cast(encounters.encounter_start_at as date) < coalesce(providers.valid_to, date '9999-12-31')
