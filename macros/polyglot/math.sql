{#
  safe_divide(n, d): n / d, NULL when d is 0 (or NULL), always a double.
  BigQuery has SAFE_DIVIDE(n, d), which returns NULL instead of raising on a
  zero divisor and returns FLOAT64 for integer or float inputs. DuckDB has no
  SAFE_DIVIDE, so the DuckDB branch reproduces both halves: NULLIF on the
  divisor for the semantics, and a cast of both sides to DOUBLE for the type
  (without it, decimal / decimal would stay DECIMAL on DuckDB while BigQuery
  answers FLOAT64).

  Float-typed on purpose. Where a model wants DECIMAL rounding (money per
  order, e.g. mart_daily_revenue.average_order_value and
  mart_customer_summary.average_order_value), do not use this macro: keep
  `round(x / nullif(y, 0), 2)` cast to money_type().
#}
{% macro safe_divide(numerator, denominator) -%}
    {{ return(adapter.dispatch('safe_divide', 'bq_duckdb_experiments')(numerator, denominator)) }}
{%- endmacro %}

{% macro default__safe_divide(numerator, denominator) -%}
    cast({{ numerator }} as {{ float_type() }}) / nullif(cast({{ denominator }} as {{ float_type() }}), 0)
{%- endmacro %}

{% macro bigquery__safe_divide(numerator, denominator) -%}
    safe_divide({{ numerator }}, {{ denominator }})
{%- endmacro %}
