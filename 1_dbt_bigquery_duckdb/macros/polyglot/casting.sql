{#
  safe_cast(expr, type): cast that returns NULL instead of failing when the value
  does not convert. Same semantics, different name: BigQuery spells it
  SAFE_CAST(<expr> AS <type>), DuckDB spells it TRY_CAST(<expr> AS <type>) and has
  no SAFE_CAST. Pass the type through a type macro, e.g.
  {{ safe_cast("'42'", int_type()) }}.
#}
{% macro safe_cast(expr, type) -%}
    {{ return(adapter.dispatch('safe_cast', 'bq_duckdb_experiments')(expr, type)) }}
{%- endmacro %}

{% macro default__safe_cast(expr, type) -%}
    try_cast({{ expr }} as {{ type }})
{%- endmacro %}

{% macro bigquery__safe_cast(expr, type) -%}
    safe_cast({{ expr }} as {{ type }})
{%- endmacro %}

{#
  to_string(expr): cast to text. The CAST syntax is identical; only the type name
  differs (DuckDB VARCHAR vs BigQuery STRING), so both branches go through
  string_type(). Usage: {{ to_string('my_column') }}
#}
{% macro to_string(expr) -%}
    {{ return(adapter.dispatch('to_string', 'bq_duckdb_experiments')(expr)) }}
{%- endmacro %}

{% macro default__to_string(expr) -%}
    cast({{ expr }} as {{ string_type() }})
{%- endmacro %}

{% macro bigquery__to_string(expr) -%}
    cast({{ expr }} as {{ string_type() }})
{%- endmacro %}

{#
  to_utc_timestamp(expr): the time-zone decision. A BigQuery TIMESTAMP is an
  absolute instant, so `cast(<expr> as timestamp)` is already UTC. DuckDB's
  bigquery extension (and the local fixture) hand it back as TIMESTAMPTZ, and a
  plain cast of that to TIMESTAMP would render it in the *session* time zone;
  `timezone('UTC', cast(<expr> as timestamptz))` returns the naive wall-clock
  time in UTC whatever the session time zone is.
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
