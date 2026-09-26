{#
  The cross-target seam.

  Sean's plan: "one single project power both with using macros to help transpile."
  That means dialect differences live HERE, not in a forked model tree. Every
  macro below is dispatched on the adapter (bigquery, duckdb), so a model can
  call `string_type()` and get a type that exists on whichever engine is running.

  These two macros are deliberately small: this card ships an empty skeleton, and
  a macro nobody calls is dead code. They exist to prove the seam works end to end
  (`dbt run-operation to_string --target duckdb`) and to set the shape the real
  macros in later cards should follow.
#}

{% macro string_type() -%}
    {{ return(adapter.dispatch('string_type', 'bq_duckdb_experiments')()) }}
{%- endmacro %}

{# Fallback for any adapter (DuckDB lands here; so does anything added later). #}
{% macro default__string_type() -%}
    varchar
{%- endmacro %}

{# BigQuery spells it `STRING`. #}
{% macro bigquery__string_type() -%}
    string
{%- endmacro %}

{# Usage shape a model would have: {{ to_string('my_column') }} #}
{% macro to_string(column_name) -%}
    cast({{ column_name }} as {{ string_type() }})
{%- endmacro %}

{#
  Types used by the staging layer and above. Money is fixed-point so sums do not
  drift; floats are for rates, ratios and coordinates only.
#}

{% macro money_type() -%}
    {{ return(adapter.dispatch('money_type', 'bq_duckdb_experiments')()) }}
{%- endmacro %}

{% macro default__money_type() -%}
    decimal(18,2)
{%- endmacro %}

{% macro bigquery__money_type() -%}
    numeric
{%- endmacro %}

{% macro float_type() -%}
    {{ return(adapter.dispatch('float_type', 'bq_duckdb_experiments')()) }}
{%- endmacro %}

{% macro default__float_type() -%}
    double
{%- endmacro %}

{% macro bigquery__float_type() -%}
    float64
{%- endmacro %}

{# A naive timestamp. Every *_at column from staging up is this type, in UTC. #}
{% macro timestamp_type() -%}
    {{ return(adapter.dispatch('timestamp_type', 'bq_duckdb_experiments')()) }}
{%- endmacro %}

{% macro default__timestamp_type() -%}
    timestamp
{%- endmacro %}

{% macro bigquery__timestamp_type() -%}
    timestamp
{%- endmacro %}

{#
  The time-zone decision. A BigQuery TIMESTAMP is an absolute instant; DuckDB's
  bigquery extension (and the local fixture) hand it back as TIMESTAMPTZ, and a
  plain cast of that to TIMESTAMP would render it in the *session* time zone.
  `timezone('UTC', <timestamptz>)` returns the naive wall-clock time in UTC
  whatever the session time zone is. On BigQuery, TIMESTAMP is already UTC.
#}
{% macro to_utc_timestamp(expr) -%}
    {{ return(adapter.dispatch('to_utc_timestamp', 'bq_duckdb_experiments')(expr)) }}
{%- endmacro %}

{% macro default__to_utc_timestamp(expr) -%}
    timezone('UTC', cast({{ expr }} as timestamptz))
{%- endmacro %}

{% macro bigquery__to_utc_timestamp(expr) -%}
    cast({{ expr }} as timestamp)
{%- endmacro %}

{#
  A surrogate key for grains with no single natural key (e.g. cohort month x
  activity month). Prefer natural keys everywhere else.

  Usage: {{ generate_surrogate_key(['user_id', 'activity_month_number']) }}
  Both branches hash the same string: the parts joined with '||'. The inputs are
  expected to be non-null (DuckDB's concat_ws skips a NULL, BigQuery's concat
  returns NULL) and should be integers or strings: a timestamp renders differently
  as text on the two engines ('... 00:00:00' vs '... 00:00:00+00'), so keys built
  from timestamps would not match across targets.
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

{#
  Date arithmetic used by the intermediate layer. Both are spelt differently on
  the two engines, so they live here.

  month_start(expr): the first instant of expr's calendar month, as a naive
  timestamp_type(). expr is a naive UTC timestamp, so this is the UTC month.
#}
{% macro month_start(expr) -%}
    {{ return(adapter.dispatch('month_start', 'bq_duckdb_experiments')(expr)) }}
{%- endmacro %}

{% macro default__month_start(expr) -%}
    cast(date_trunc('month', {{ expr }}) as {{ timestamp_type() }})
{%- endmacro %}

{% macro bigquery__month_start(expr) -%}
    timestamp_trunc({{ expr }}, month)
{%- endmacro %}

{# seconds_between(start, end): end - start in seconds, as float_type() (microsecond precision). #}
{% macro seconds_between(start_expr, end_expr) -%}
    {{ return(adapter.dispatch('seconds_between', 'bq_duckdb_experiments')(start_expr, end_expr)) }}
{%- endmacro %}

{% macro default__seconds_between(start_expr, end_expr) -%}
    cast(date_diff('microsecond', {{ start_expr }}, {{ end_expr }}) as {{ float_type() }}) / 1000000.0
{%- endmacro %}

{% macro bigquery__seconds_between(start_expr, end_expr) -%}
    cast(timestamp_diff({{ end_expr }}, {{ start_expr }}, microsecond) as {{ float_type() }}) / 1000000.0
{%- endmacro %}

{#
  month_number(expr): yyyymm as an integer (e.g. 202403). Used as a surrogate-key
  part instead of a month timestamp, because integers render as the same text on
  both engines and timestamps do not. Same syntax on both engines.
#}
{% macro month_number(expr) -%}
    (extract(year from {{ expr }}) * 100 + extract(month from {{ expr }}))
{%- endmacro %}
