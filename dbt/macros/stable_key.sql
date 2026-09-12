{% macro stable_key(expression) -%}
lower(to_hex(md5(to_utf8(cast({{ expression }} as varchar)))))
{%- endmacro %}
