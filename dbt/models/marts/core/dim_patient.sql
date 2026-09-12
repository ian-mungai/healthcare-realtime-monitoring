select
    {{ stable_key("patient_id") }} as patient_key,
    patient_id,
    concat('Patient/', patient_id) as patient_reference,
    'HAPI FHIR R4' as source_system,
    'synthetic' as data_classification
from {{ ref('stg_fhir_observations') }}
where patient_id is not null
group by patient_id
