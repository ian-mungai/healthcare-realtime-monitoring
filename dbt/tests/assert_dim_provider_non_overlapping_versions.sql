select
    earlier.provider_version_key as earlier_provider_version_key,
    later.provider_version_key as later_provider_version_key
from {{ ref('dim_provider') }} as earlier
inner join {{ ref('dim_provider') }} as later
    on earlier.provider_npi = later.provider_npi
    and earlier.provider_version_key < later.provider_version_key
where earlier.valid_from < coalesce(later.valid_to, date '9999-12-31')
    and later.valid_from < coalesce(earlier.valid_to, date '9999-12-31')
