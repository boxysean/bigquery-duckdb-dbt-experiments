{#
  safe_cast(expr, type): cast that returns NULL instead of failing when the value
  does not convert. Same semantics, different name: BigQuery spells it
  SAFE_CAST(<expr> AS <type>), Spark spells it TRY_CAST(<expr> AS <type>) and has
  no SAFE_CAST (measured: try_cast('nope' as bigint) is NULL). Pass the type
  through a type macro, e.g. {{ safe_cast("'42'", int_type()) }}.
#}
{% macro safe_cast(expr, type) -%}
    {{ return(adapter.dispatch('safe_cast', 'bq_spark_experiments')(expr, type)) }}
{%- endmacro %}

{% macro default__safe_cast(expr, type) -%}
    try_cast({{ expr }} as {{ type }})
{%- endmacro %}

{% macro bigquery__safe_cast(expr, type) -%}
    safe_cast({{ expr }} as {{ type }})
{%- endmacro %}

{#
  to_string(expr): cast to text. The CAST syntax and the type name (STRING) are
  identical on both engines; the dispatch is kept so the seam has one shape.
  Usage: {{ to_string('my_column') }}
#}
{% macro to_string(expr) -%}
    {{ return(adapter.dispatch('to_string', 'bq_spark_experiments')(expr)) }}
{%- endmacro %}

{% macro default__to_string(expr) -%}
    cast({{ expr }} as {{ string_type() }})
{%- endmacro %}

{% macro bigquery__to_string(expr) -%}
    cast({{ expr }} as {{ string_type() }})
{%- endmacro %}

{#
  to_utc_timestamp(expr): the time-zone decision. A BigQuery TIMESTAMP is an
  absolute instant, so `cast(<expr> as timestamp)` is already UTC. A Spark
  TIMESTAMP is also an instant (TIMESTAMP_LTZ), but it is RENDERED, truncated
  and turned into a date in the SESSION time zone. This project's Spark session
  is pinned to UTC (measured: current_timezone() = 'UTC', proved again by
  polyglot_selfcheck), so the Spark branch is the same plain cast.

  The gotcha this depends on, measured on Spark 4.2.0 with
  spark.sql.session.timeZone=Europe/Vienna: the instant itself is kept
  (`timestamp '2024-03-15 13:45:00+02:00'` -> same unix_micros), but it renders
  as '2024-03-15 12:45:00', a naive literal is read as Vienna time (1 hour off),
  and an instant at 23:30 UTC on 2024-03-31 becomes the date 2024-04-01, month
  '2024-04'. A non-UTC session silently moves every day and month boundary.
  Spark has its own to_utc_timestamp(ts, tz) function with different semantics
  (it shifts wall-clock time); this macro does not use it.
#}
{% macro to_utc_timestamp(expr) -%}
    {{ return(adapter.dispatch('to_utc_timestamp', 'bq_spark_experiments')(expr)) }}
{%- endmacro %}

{% macro default__to_utc_timestamp(expr) -%}
    cast({{ expr }} as {{ timestamp_type() }})
{%- endmacro %}

{% macro bigquery__to_utc_timestamp(expr) -%}
    cast({{ expr }} as timestamp)
{%- endmacro %}
