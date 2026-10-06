{#
  generate_surrogate_key(cols): a surrogate key for grains with no single natural
  key (e.g. cohort month x activity month). Prefer natural keys everywhere else.

  Usage: {{ generate_surrogate_key(['user_id', 'activity_month_number']) }}
  Both branches hash the same string, the parts joined with '||', but the two
  engines' concatenation differs: Spark has CONCAT_WS and accepts integer
  arguments (`md5(concat_ws('||', a, b))`, hex text already; measured:
  md5(concat_ws('||', 1, 'x')) = df6729622b8fb993f31b1ba95a27e5cc and a
  month_number() part hashes as its yyyymm digits); BigQuery has no CONCAT_WS,
  its CONCAT accepts only STRING/BYTES, and MD5 returns BYTES
  (`to_hex(md5(concat(cast(a as string), '||', cast(b as string))))`). The inputs
  are expected to be non-null (Spark's concat_ws SKIPS a NULL part, measured:
  md5(concat_ws('||', 1, null)) = md5('1'); BigQuery's concat returns NULL) and
  should be integers or strings: a timestamp renders differently as text on the
  two engines ('2024-03-15 13:45:00' vs '2024-03-15 13:45:00+00'), so keys built
  from timestamps would not match across targets.
#}
{% macro generate_surrogate_key(cols) -%}
    {{ return(adapter.dispatch('generate_surrogate_key', 'bq_spark_experiments')(cols)) }}
{%- endmacro %}

{% macro default__generate_surrogate_key(cols) -%}
    md5(concat_ws('||', {{ cols | join(', ') }}))
{%- endmacro %}

{#
  BigQuery's concat() accepts only STRING/BYTES arguments, so every column is
  cast to string first (an INT64 or TIMESTAMP argument is a type error), and the
  '||' separator is interleaved so the hashed string equals Spark's concat_ws.
#}
{% macro bigquery__generate_surrogate_key(cols) -%}
    {%- set parts = [] -%}
    {%- for col in cols -%}
        {%- do parts.append(to_string(col)) -%}
    {%- endfor -%}
    to_hex(md5(concat({{ parts | join(", '||', ") }})))
{%- endmacro %}
