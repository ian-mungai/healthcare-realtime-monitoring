with observations as (
    select
        *,
        {{ stable_key("coalesce(nullif(trim(encounter_id), ''), concat('__legacy_unknown__|', patient_id))") }} as encounter_key
    from {{ ref('stg_fhir_observations') }}
)

select
    {{ stable_key("concat(observations.observation_id, '|', observations.loinc_code)") }} as fact_observation_key,
    {{ stable_key("observations.patient_id") }} as patient_key,
    observations.encounter_key,
    encounters.provider_key,
    encounters.provider_version_key,
    {{ stable_key("observations.loinc_code") }} as observation_type_key,
    cast(date_format(cast(observations.effective_datetime as timestamp), '%Y%m%d') as integer) as date_key,
    observations.observation_id,
    observations.patient_id,
    observations.encounter_id,
    observations.observation_type,
    observations.loinc_code,
    observations.value,
    observations.unit,
    observations.effective_datetime,
    observations.received_at,
    observations.source,
    observations.year,
    observations.month,
    observations.day
from observations
inner join {{ ref('dim_encounter') }} as encounters
    on observations.encounter_key = encounters.encounter_key
