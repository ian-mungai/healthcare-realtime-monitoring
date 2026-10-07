{#- Lowercase hexadecimal MD5 of the expression's text, the same value on Athena and Postgres. -#}
{% macro stable_key(expression) -%}
    {{ return(adapter.dispatch('stable_key', 'healthcare_realtime')(expression)) }}
{%- endmacro %}

{% macro default__stable_key(expression) -%}
lower(to_hex(md5(to_utf8(cast({{ expression }} as varchar)))))
{%- endmacro %}

{% macro postgres__stable_key(expression) -%}
md5(cast({{ expression }} as text))
{%- endmacro %}
