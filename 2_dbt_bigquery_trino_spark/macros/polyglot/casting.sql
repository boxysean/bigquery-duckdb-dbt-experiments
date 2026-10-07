{#
  safe_cast(expr, type): a cast that returns NULL instead of failing. BigQuery
  SAFE_CAST(<expr> AS <type>); Trino TRY_CAST(<expr> AS <type>) (no SAFE_CAST).
#}
{% macro safe_cast(expr, type) -%}
    {{ return(adapter.dispatch('safe_cast', 'bq_trino_experiments')(expr, type)) }}
{%- endmacro %}

{% macro trino__safe_cast(expr, type) -%}
    try_cast({{ expr }} as {{ type }})
{%- endmacro %}

{% macro bigquery__safe_cast(expr, type) -%}
    safe_cast({{ expr }} as {{ type }})
{%- endmacro %}

{#
  to_string(expr): cast to text, through string_type() (Trino VARCHAR, BigQuery STRING).
#}
{% macro to_string(expr) -%}
    {{ return(adapter.dispatch('to_string', 'bq_trino_experiments')(expr)) }}
{%- endmacro %}

{% macro trino__to_string(expr) -%}
    cast({{ expr }} as {{ string_type() }})
{%- endmacro %}

{% macro bigquery__to_string(expr) -%}
    cast({{ expr }} as {{ string_type() }})
{%- endmacro %}

{#
  to_utc_timestamp(expr): the time-zone decision. A BigQuery TIMESTAMP is an absolute
  instant, so `cast(<expr> as timestamp)` is already UTC.

  On the lakehouse the sources are Iceberg `timestamptz`, which Trino reads as
  timestamp(6) with time zone. Casting that straight to a naive timestamp would keep
  the wall clock of whatever zone the value carries; `at time zone 'UTC'` moves it to
  UTC first, so the result is the naive UTC wall clock whatever the session time zone.
  The inner cast makes a naive input explicit instead of relying on the session zone.
#}
{% macro to_utc_timestamp(expr) -%}
    {{ return(adapter.dispatch('to_utc_timestamp', 'bq_trino_experiments')(expr)) }}
{%- endmacro %}

{% macro trino__to_utc_timestamp(expr) -%}
    cast(cast({{ expr }} as timestamp(6) with time zone) at time zone 'UTC' as {{ timestamp_type() }})
{%- endmacro %}

{% macro bigquery__to_utc_timestamp(expr) -%}
    cast({{ expr }} as timestamp)
{%- endmacro %}
