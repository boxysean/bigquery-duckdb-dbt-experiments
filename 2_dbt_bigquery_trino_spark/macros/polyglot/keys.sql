{#
  generate_surrogate_key(cols): a surrogate key for grains with no single natural key.
  Every engine hashes the same string, the parts cast to text and joined with '||',
  and renders the MD5 as LOWERCASE hex:
    * BigQuery: to_hex(md5(concat(a, '||', b)))      (MD5 returns BYTES; TO_HEX is lower)
    * Trino:    lower(to_hex(md5(to_utf8(concat_ws('||', a, b)))))
                (MD5 takes VARBINARY, hence TO_UTF8; Trino's TO_HEX is UPPERCASE)
  Inputs must be non-null integers or strings: a timestamp renders differently as text
  on each engine, so keys built from timestamps would not match across targets.
#}
{% macro generate_surrogate_key(cols) -%}
    {{ return(adapter.dispatch('generate_surrogate_key', 'bq_trino_experiments')(cols)) }}
{%- endmacro %}

{% macro trino__generate_surrogate_key(cols) -%}
    {%- set parts = [] -%}
    {%- for col in cols -%}
        {%- do parts.append(to_string(col)) -%}
    {%- endfor -%}
    lower(to_hex(md5(to_utf8(concat_ws('||', {{ parts | join(', ') }})))))
{%- endmacro %}

{% macro bigquery__generate_surrogate_key(cols) -%}
    {%- set parts = [] -%}
    {%- for col in cols -%}
        {%- do parts.append(to_string(col)) -%}
    {%- endfor -%}
    to_hex(md5(concat({{ parts | join(", '||', ") }})))
{%- endmacro %}
