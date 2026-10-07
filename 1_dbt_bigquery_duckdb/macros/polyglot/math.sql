{#
  safe_divide(n, d): n / d, NULL when d is 0 (or NULL), always a double.
  BigQuery has SAFE_DIVIDE(n, d), which returns NULL instead of raising on a
  zero divisor, but returns the type of its inputs. DuckDB has no SAFE_DIVIDE,
  so the DuckDB branch uses NULLIF on the divisor for the semantics. For the
  type, both branches cast both sides to float_type() before dividing: only
  integer inputs would give FLOAT64 for free, so the cast is what keeps a
  NUMERIC/DECIMAL call site float-typed on both targets.

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
    safe_divide(cast({{ numerator }} as {{ float_type() }}), cast({{ denominator }} as {{ float_type() }}))
{%- endmacro %}
