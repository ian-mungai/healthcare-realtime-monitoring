select
    {{ stable_key("loinc_code") }} as observation_type_key,
    observation_type,
    loinc_code,
    unit,
    'http://loinc.org' as code_system
from {{ ref('stg_fhir_observations') }}
where loinc_code is not null
group by
    observation_type,
    loinc_code,
    unit
