{#
  Array generators.

  `unnest(...)` is deliberately NOT a macro: the name and the semantics (one row
  per array element, used in FROM or as a table function over an array) are
  identical on BigQuery and DuckDB, so a wrapper would only hide plain SQL.
  Do not add one. What differs is the ALIAS in FROM: see unnest_alias below.
#}

{#
  unnest_alias(column): the alias that names the element column of an unnest in
  FROM, `cross join unnest(<array>) as {{ unnest_alias('date_day') }}`.
  BigQuery binds `unnest(<array>) as date_day` to the element itself. DuckDB
  binds the same alias to the TABLE, so `date_day` would be a whole-row
  STRUCT(unnest DATE) (measured on DuckDB 1.5.5); it needs the column-alias form
  `as <table>(date_day)`, which BigQuery does not accept. The DuckDB table alias
  is `<column>__unnest`, so two unnests in one query need different columns.
#}
{% macro unnest_alias(column) -%}
    {{ return(adapter.dispatch('unnest_alias', 'bq_duckdb_experiments')(column)) }}
{%- endmacro %}

{% macro default__unnest_alias(column) -%}
    {{ column }}__unnest({{ column }})
{%- endmacro %}

{% macro bigquery__unnest_alias(column) -%}
    {{ column }}
{%- endmacro %}

{#
  generate_series(start, stop[, step]): an integer array from start to stop
  inclusive. BigQuery's array generator is GENERATE_ARRAY(start, stop[, step]);
  DuckDB's is GENERATE_SERIES(start, stop[, step]) (which returns a list, also
  inclusive). BigQuery has no GENERATE_SERIES and DuckDB has no GENERATE_ARRAY.
#}
{% macro generate_series(start_expr, stop_expr, step=none) -%}
    {{ return(adapter.dispatch('generate_series', 'bq_duckdb_experiments')(start_expr, stop_expr, step)) }}
{%- endmacro %}

{% macro default__generate_series(start_expr, stop_expr, step=none) -%}
    generate_series({{ start_expr }}, {{ stop_expr }}{% if step is not none %}, {{ step }}{% endif %})
{%- endmacro %}

{% macro bigquery__generate_series(start_expr, stop_expr, step=none) -%}
    generate_array({{ start_expr }}, {{ stop_expr }}{% if step is not none %}, {{ step }}{% endif %})
{%- endmacro %}

{#
  generate_date_series(start, stop, step='1 day'): an array of DATEs from start
  to stop inclusive. BigQuery has GENERATE_DATE_ARRAY(start, stop, INTERVAL n
  part), which returns ARRAY<DATE>. DuckDB has no date-array generator: its
  GENERATE_SERIES over dates with an INTERVAL step returns TIMESTAMP[], so the
  DuckDB branch casts the result back to DATE[] to keep the element type equal.
  step must be '<n> <part>' with n >= 1 and part one of day|week|month|quarter|
  year; anything else is a compiler error.
  Caveat for month/quarter/year steps: DuckDB adds the interval to the PREVIOUS
  element, so a month-end start drifts ('2024-01-31' -> 02-29 -> 03-29, measured
  on DuckDB 1.5.5). BigQuery's behaviour for that case is not verified here.
  Start month steps on the 1st to stay unambiguous.
#}
{% macro generate_date_series(start_expr, stop_expr, step='1 day') -%}
    {%- set match = modules.re.match('^\s*([0-9]+)\s+(day|week|month|quarter|year)\s*$', step | string | lower) -%}
    {%- if not match or (match.group(1) | int) < 1 -%}
        {{ exceptions.raise_compiler_error(
            "generate_date_series(start, stop, step): step must be '<n> <day|week|month|quarter|year>' with n >= 1, got '" ~ step ~ "'") }}
    {%- endif -%}
    {%- set interval = (match.group(1) | int) ~ ' ' ~ match.group(2) -%}
    {{ return(adapter.dispatch('generate_date_series', 'bq_duckdb_experiments')(start_expr, stop_expr, interval)) }}
{%- endmacro %}

{% macro default__generate_date_series(start_expr, stop_expr, step) -%}
    cast(generate_series({{ start_expr }}, {{ stop_expr }}, interval {{ step }}) as date[])
{%- endmacro %}

{% macro bigquery__generate_date_series(start_expr, stop_expr, step) -%}
    generate_date_array({{ start_expr }}, {{ stop_expr }}, interval {{ step }})
{%- endmacro %}
