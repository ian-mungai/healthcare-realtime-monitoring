{#-
    SQL that differs between Athena (Trino) and the local Postgres warehouse. The default branch is the Athena SQL the
    models used before the local target existed, so Athena output is unchanged.
-#}

{#- Integer value of the first `digits` hexadecimal characters of a key, for deterministic split buckets. -#}
{% macro hex_prefix_number(expression, digits) -%}
    {{ return(adapter.dispatch('hex_prefix_number', 'healthcare_realtime')(expression, digits)) }}
{%- endmacro %}

{% macro default__hex_prefix_number(expression, digits) -%}
from_base(substr({{ expression }}, 1, {{ digits }}), 16)
{%- endmacro %}

{% macro postgres__hex_prefix_number(expression, digits) -%}
cast(cast(('x' || lpad(substr({{ expression }}, 1, {{ digits }}), 16, '0')) as bit(64)) as bigint)
{%- endmacro %}

{#- Calendar date key as an integer YYYYMMDD. -#}
{% macro date_key(expression) -%}
    {{ return(adapter.dispatch('date_key', 'healthcare_realtime')(expression)) }}
{%- endmacro %}

{% macro default__date_key(expression) -%}
cast(date_format(cast({{ expression }} as timestamp), '%Y%m%d') as integer)
{%- endmacro %}

{% macro postgres__date_key(expression) -%}
cast(to_char(cast({{ expression }} as timestamp), 'YYYYMMDD') as integer)
{%- endmacro %}

{#- A numbered date part: year, quarter, month, day, iso_day_of_week (Monday 1) or iso_week. -#}
{% macro date_part_number(part, expression) -%}
    {{ return(adapter.dispatch('date_part_number', 'healthcare_realtime')(part, expression)) }}
{%- endmacro %}

{% macro default__date_part_number(part, expression) -%}
    {%- set functions = {'year': 'year', 'quarter': 'quarter', 'month': 'month', 'day': 'day', 'iso_day_of_week': 'day_of_week', 'iso_week': 'week'} -%}
{{ functions[part] }}({{ expression }})
{%- endmacro %}

{% macro postgres__date_part_number(part, expression) -%}
    {%- set fields = {'year': 'year', 'quarter': 'quarter', 'month': 'month', 'day': 'day', 'iso_day_of_week': 'isodow', 'iso_week': 'week'} -%}
cast(extract({{ fields[part] }} from {{ expression }}) as integer)
{%- endmacro %}

{#- English month or day name. -#}
{% macro calendar_name(part, expression) -%}
    {{ return(adapter.dispatch('calendar_name', 'healthcare_realtime')(part, expression)) }}
{%- endmacro %}

{% macro default__calendar_name(part, expression) -%}
date_format(cast({{ expression }} as timestamp), '{{ "%M" if part == "month" else "%W" }}')
{%- endmacro %}

{% macro postgres__calendar_name(part, expression) -%}
to_char(cast({{ expression }} as timestamp), '{{ "FMMonth" if part == "month" else "FMDay" }}')
{%- endmacro %}

{#- Timestamp plus a whole number of minutes. -#}
{% macro add_minutes(minutes, expression) -%}
    {{ return(adapter.dispatch('add_minutes', 'healthcare_realtime')(minutes, expression)) }}
{%- endmacro %}

{% macro default__add_minutes(minutes, expression) -%}
date_add('minute', {{ minutes }}, {{ expression }})
{%- endmacro %}

{% macro postgres__add_minutes(minutes, expression) -%}
({{ expression }} + interval '{{ minutes }} minutes')
{%- endmacro %}

{#- Whole seconds from the first timestamp to the second. -#}
{% macro seconds_between(start_expression, end_expression) -%}
    {{ return(adapter.dispatch('seconds_between', 'healthcare_realtime')(start_expression, end_expression)) }}
{%- endmacro %}

{% macro default__seconds_between(start_expression, end_expression) -%}
date_diff('second', {{ start_expression }}, {{ end_expression }})
{%- endmacro %}

{% macro postgres__seconds_between(start_expression, end_expression) -%}
cast(extract(epoch from ({{ end_expression }} - {{ start_expression }})) as bigint)
{%- endmacro %}
