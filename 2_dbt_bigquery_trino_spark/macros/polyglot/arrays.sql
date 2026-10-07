{#
  Array generators.

  `unnest(...)` is deliberately NOT a macro: the name and the semantics are the same on
  BigQuery and Trino. What differs is the ALIAS in FROM: see unnest_alias below.

  Arrays are 1-based on Trino (element_at(a, 1), a[1]) and on Spark; BigQuery offers both
  OFFSET (0-based) and ORDINAL (1-based). No model indexes an array today; if one does,
  add a macro rather than hand-translating an index.
#}

{#
  unnest_alias(column): the alias that names the element column of an unnest in FROM,
  `cross join unnest(<array>) as {{ unnest_alias('date_day') }}`. BigQuery binds
  `unnest(<array>) as date_day` to the element itself. Trino requires the column-alias
  form `as <table>(date_day)`, which BigQuery does not accept.
#}
{% macro unnest_alias(column) -%}
    {{ return(adapter.dispatch('unnest_alias', 'bq_trino_experiments')(column)) }}
{%- endmacro %}

{% macro trino__unnest_alias(column) -%}
    {{ column }}__unnest({{ column }})
{%- endmacro %}

{% macro bigquery__unnest_alias(column) -%}
    {{ column }}
{%- endmacro %}

{#
  generate_series(start, stop[, step]): an integer array, inclusive. BigQuery
  GENERATE_ARRAY; Trino SEQUENCE (also inclusive, returns array(bigint)).
#}
{% macro generate_series(start_expr, stop_expr, step=none) -%}
    {{ return(adapter.dispatch('generate_series', 'bq_trino_experiments')(start_expr, stop_expr, step)) }}
{%- endmacro %}

{% macro trino__generate_series(start_expr, stop_expr, step=none) -%}
    sequence(cast({{ start_expr }} as bigint), cast({{ stop_expr }} as bigint){% if step is not none %}, cast({{ step }} as bigint){% endif %})
{%- endmacro %}

{% macro bigquery__generate_series(start_expr, stop_expr, step=none) -%}
    generate_array({{ start_expr }}, {{ stop_expr }}{% if step is not none %}, {{ step }}{% endif %})
{%- endmacro %}

{#
  generate_date_series(start, stop, step='1 day'): an array of DATEs, inclusive.
  BigQuery GENERATE_DATE_ARRAY(start, stop, INTERVAL n part). Trino SEQUENCE over dates
  takes an interval literal, but only DAY or MONTH units: a week is rendered as 7n days,
  a quarter as 3n months, a year as 12n months. Trino computes start + i * step, so a
  month-end start does not drift.
#}
{% macro generate_date_series(start_expr, stop_expr, step='1 day') -%}
    {%- set match = modules.re.match('^\s*([0-9]+)\s+(day|week|month|quarter|year)\s*$', step | string | lower) -%}
    {%- if not match or (match.group(1) | int) < 1 -%}
        {{ exceptions.raise_compiler_error(
            "generate_date_series(start, stop, step): step must be '<n> <day|week|month|quarter|year>' with n >= 1, got '" ~ step ~ "'") }}
    {%- endif -%}
    {%- set interval = (match.group(1) | int) ~ ' ' ~ match.group(2) -%}
    {{ return(adapter.dispatch('generate_date_series', 'bq_trino_experiments')(start_expr, stop_expr, interval)) }}
{%- endmacro %}

{% macro trino__generate_date_series(start_expr, stop_expr, step) -%}
    {%- set n, part = step.split(' ') -%}
    {%- set n = n | int -%}
    {%- if part == 'week' -%}{%- set n, part = n * 7, 'day' -%}
    {%- elif part == 'quarter' -%}{%- set n, part = n * 3, 'month' -%}
    {%- elif part == 'year' -%}{%- set n, part = n * 12, 'month' -%}
    {%- endif -%}
    sequence(cast({{ start_expr }} as date), cast({{ stop_expr }} as date), interval '{{ n }}' {{ part }})
{%- endmacro %}

{% macro bigquery__generate_date_series(start_expr, stop_expr, step) -%}
    generate_date_array({{ start_expr }}, {{ stop_expr }}, interval {{ step }})
{%- endmacro %}
