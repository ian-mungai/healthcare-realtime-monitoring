with typed_history as (
    select
        trim(provider_npi) as provider_npi,
        trim(provider_name) as provider_name,
        trim(taxonomy_code) as taxonomy_code,
        trim(taxonomy_description) as taxonomy_description,
        trim(provider_state) as provider_state,
        cast(valid_from as date) as valid_from,
        cast(nullif(trim(valid_to), '') as date) as valid_to,
        cast(is_current as boolean) as is_current,
        trim(data_source) as data_source
    from {{ ref('provider_history') }}
)

select
    {{ stable_key("concat(provider_npi, '|', cast(valid_from as varchar))") }} as provider_version_key,
    {{ stable_key("provider_npi") }} as provider_key,
    provider_npi,
    provider_name,
    taxonomy_code,
    taxonomy_description,
    provider_state,
    valid_from,
    valid_to,
    is_current,
    data_source
from typed_history
