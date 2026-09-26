{#
  generate_surrogate_key(cols): a surrogate key for grains with no single natural
  key (e.g. cohort month x activity month). Prefer natural keys everywhere else.

  Usage: {{ generate_surrogate_key(['user_id', 'activity_month_number']) }}
  Both branches hash the same string, the parts joined with '||', but the two
  engines' concatenation differs: DuckDB has CONCAT_WS and accepts any type
  (`md5(concat_ws('||', a, b))`, hex text already); BigQuery has no CONCAT_WS,
  its CONCAT accepts only STRING/BYTES, and MD5 returns BYTES
  (`to_hex(md5(concat(cast(a as string), '||', cast(b as string))))`). The inputs
  are expected to be non-null (DuckDB's concat_ws skips a NULL, BigQuery's concat
  returns NULL) and should be integers or strings: a timestamp renders
  differently as text on the two engines ('... 00:00:00' vs '... 00:00:00+00'),
  so keys built from timestamps would not match across targets.
#}
{% macro generate_surrogate_key(cols) -%}
    {{ return(adapter.dispatch('generate_surrogate_key', 'bq_duckdb_experiments')(cols)) }}
{%- endmacro %}

{% macro default__generate_surrogate_key(cols) -%}
    md5(concat_ws('||', {{ cols | join(', ') }}))
{%- endmacro %}

{#
  BigQuery's concat() accepts only STRING/BYTES arguments, so every column is
  cast to string first (an INT64 or TIMESTAMP argument is a type error), and the
  '||' separator is interleaved so the hashed string equals DuckDB's concat_ws.
#}
{% macro bigquery__generate_surrogate_key(cols) -%}
    {%- set parts = [] -%}
    {%- for col in cols -%}
        {%- do parts.append(to_string(col)) -%}
    {%- endfor -%}
    to_hex(md5(concat({{ parts | join(", '||', ") }})))
{%- endmacro %}
