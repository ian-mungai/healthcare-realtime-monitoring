with observation_dates as (
    select distinct cast(effective_datetime as date) as full_date
    from {{ ref('stg_fhir_observations') }}
    where effective_datetime is not null
)

select
    cast(date_format(cast(full_date as timestamp), '%Y%m%d') as integer) as date_key,
    full_date,
    year(full_date) as calendar_year,
    quarter(full_date) as calendar_quarter,
    month(full_date) as month_number,
    date_format(cast(full_date as timestamp), '%M') as month_name,
    day(full_date) as day_of_month,
    day_of_week(full_date) as iso_day_of_week,
    date_format(cast(full_date as timestamp), '%W') as day_name,
    week(full_date) as iso_week_of_year
from observation_dates
