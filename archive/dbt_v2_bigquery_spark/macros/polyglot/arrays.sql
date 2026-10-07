{#
  Array generators, and the one FROM-clause fragment in the seam.

  The root project's rule is that `unnest(...)` is deliberately NOT a macro,
  because its name and semantics were identical on both of that project's
  engines. That rule breaks here: Spark has no `unnest` at all (measured on
  Spark 4.2.0: `select ... from unnest(...)` fails with
  UNRESOLVABLE_TABLE_VALUED_FUNCTION "Could not resolve unnest to a
  table-valued function"). Spark explodes an array into rows with
  `lateral view explode(...)`, which is a different FROM-clause shape, so the
  whole fragment becomes a macro: explode_array_rows below.
#}

{#
  explode_array_rows(array_expr, alias): a FROM-clause fragment that joins one
  row per array element onto the FROM item before it, the element column named
  <alias>. Usage, directly after a FROM item:

      from bounds
      {{ explode_array_rows(generate_date_series('first_date', 'last_date'), 'date_day') }}

  BigQuery: `cross join unnest(<array_expr>) as <alias>` (the alias binds to the
  element). Spark: `lateral view explode(<array_expr>) <alias>__arr as <alias>`
  (a LATERAL VIEW needs a table alias as well as the column alias; the table
  alias is `<alias>__arr`, so two explodes in one query need different
  aliases). Both drop the outer row when the array is empty (measured on Spark:
  explode(array()) gives 0 rows; BigQuery's CROSS JOIN UNNEST of [] gives 0
  rows by definition of the cross join). A LATERAL VIEW must follow a FROM
  item, so `from {{ explode_array_rows(...) }}` with nothing before it is not
  valid on Spark; select from a one-row subquery first.
#}
{% macro explode_array_rows(array_expr, alias) -%}
    {%- if alias is not string or not modules.re.match('^[A-Za-z_][A-Za-z0-9_]*$', alias) -%}
        {{ exceptions.raise_compiler_error(
            "explode_array_rows(array_expr, alias): alias must be a plain identifier, got '" ~ alias ~ "'") }}
    {%- endif -%}
    {{ return(adapter.dispatch('explode_array_rows', 'bq_spark_experiments')(array_expr, alias)) }}
{%- endmacro %}

{% macro default__explode_array_rows(array_expr, alias) -%}
    lateral view explode({{ array_expr }}) {{ alias }}__arr as {{ alias }}
{%- endmacro %}

{% macro bigquery__explode_array_rows(array_expr, alias) -%}
    cross join unnest({{ array_expr }}) as {{ alias }}
{%- endmacro %}

{#
  generate_series(start, stop[, step]): an integer array from start to stop
  inclusive. BigQuery's array generator is GENERATE_ARRAY(start, stop[, step]);
  Spark's is SEQUENCE(start, stop[, step]) (measured: sequence(1, 9, 3) =
  [1, 4, 7]). BigQuery has no SEQUENCE and Spark has no GENERATE_ARRAY.
  Caveat, measured on Spark 4.2.0: when start > stop, Spark's sequence(1, 0)
  counts DOWN ([1, 0]) and sequence(1, 0, 1) raises "Illegal sequence
  boundaries"; BigQuery's GENERATE_ARRAY returns an empty array for that case.
  Keep start <= stop.
#}
{% macro generate_series(start_expr, stop_expr, step=none) -%}
    {{ return(adapter.dispatch('generate_series', 'bq_spark_experiments')(start_expr, stop_expr, step)) }}
{%- endmacro %}

{% macro default__generate_series(start_expr, stop_expr, step=none) -%}
    sequence({{ start_expr }}, {{ stop_expr }}{% if step is not none %}, {{ step }}{% endif %})
{%- endmacro %}

{% macro bigquery__generate_series(start_expr, stop_expr, step=none) -%}
    generate_array({{ start_expr }}, {{ stop_expr }}{% if step is not none %}, {{ step }}{% endif %})
{%- endmacro %}

{#
  generate_date_series(start, stop, step='1 day'): an array of DATEs from start
  to stop inclusive. BigQuery has GENERATE_DATE_ARRAY(start, stop, INTERVAL n
  part); Spark's SEQUENCE(start, stop, INTERVAL n part) over dates returns
  ARRAY<DATE> as well (measured: typeof = array<date>), so no cast is needed.
  step must be '<n> <part>' with n >= 1 and part one of day|week|month|quarter|
  year; anything else is a compiler error.
  Spark has no QUARTER interval unit (measured: `interval 1 quarter` is a
  PARSE_SYNTAX_ERROR), so the Spark branch renders a quarter step as
  `interval <3n> month`. Month steps on Spark count from the START, not the
  previous element (measured: '2024-01-31' -> 02-29 -> 03-31 -> 04-30, no
  drift). The same caveat as generate_series applies when start > stop:
  Spark raises "Illegal sequence boundaries".
#}
{% macro generate_date_series(start_expr, stop_expr, step='1 day') -%}
    {%- set match = modules.re.match('^\s*([0-9]+)\s+(day|week|month|quarter|year)\s*$', step | string | lower) -%}
    {%- if not match or (match.group(1) | int) < 1 -%}
        {{ exceptions.raise_compiler_error(
            "generate_date_series(start, stop, step): step must be '<n> <day|week|month|quarter|year>' with n >= 1, got '" ~ step ~ "'") }}
    {%- endif -%}
    {{ return(adapter.dispatch('generate_date_series', 'bq_spark_experiments')(start_expr, stop_expr, match.group(1) | int, match.group(2))) }}
{%- endmacro %}

{% macro default__generate_date_series(start_expr, stop_expr, n, part) -%}
    {%- if part == 'quarter' -%}
        {%- set n = n * 3 -%}
        {%- set part = 'month' -%}
    {%- endif -%}
    sequence({{ start_expr }}, {{ stop_expr }}, interval {{ n }} {{ part }})
{%- endmacro %}

{% macro bigquery__generate_date_series(start_expr, stop_expr, n, part) -%}
    generate_date_array({{ start_expr }}, {{ stop_expr }}, interval {{ n }} {{ part }})
{%- endmacro %}
