with observation_dates as (
    select distinct cast(effective_datetime as date) as full_date
    from {{ ref('stg_fhir_observations') }}
    where effective_datetime is not null
)

select
    {{ date_key('full_date') }} as date_key,
    full_date,
    {{ date_part_number('year', 'full_date') }} as calendar_year,
    {{ date_part_number('quarter', 'full_date') }} as calendar_quarter,
    {{ date_part_number('month', 'full_date') }} as month_number,
    {{ calendar_name('month', 'full_date') }} as month_name,
    {{ date_part_number('day', 'full_date') }} as day_of_month,
    {{ date_part_number('iso_day_of_week', 'full_date') }} as iso_day_of_week,
    {{ calendar_name('day', 'full_date') }} as day_name,
    {{ date_part_number('iso_week', 'full_date') }} as iso_week_of_year
from observation_dates
