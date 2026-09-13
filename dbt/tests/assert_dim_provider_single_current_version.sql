select provider_npi
from {{ ref('dim_provider') }}
group by provider_npi
having sum(case when is_current then 1 else 0 end) != 1
