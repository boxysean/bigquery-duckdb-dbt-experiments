{#
  safe_divide(n, d): n / d, NULL when d is 0 (or NULL), always a double.
  BigQuery has SAFE_DIVIDE(n, d), which returns NULL instead of raising on a
  zero divisor, but returns the type of its inputs. Spark has no SAFE_DIVIDE;
  its TRY_DIVIDE(n, d) has the same NULL-on-zero semantics (measured:
  try_divide(1.0, 0.0) is NULL, try_divide(1.0, 4.0) = 0.25). Plain `/` is not
  a substitute on Spark 4: with ANSI mode on (the default) a zero divisor
  raises. For the type, both branches cast both sides to float_type() before
  dividing, which is what keeps a NUMERIC/DECIMAL call site float-typed on both
  targets (measured on Spark: typeof = double for decimal(18,2) inputs).

  Float-typed on purpose. Where a model wants DECIMAL rounding (money per
  order, e.g. mart_daily_revenue.average_order_value and
  mart_customer_summary.average_order_value), do not use this macro: keep
  `round(x / nullif(y, 0), 2)` cast to money_type().
#}
{% macro safe_divide(numerator, denominator) -%}
    {{ return(adapter.dispatch('safe_divide', 'bq_spark_experiments')(numerator, denominator)) }}
{%- endmacro %}

{% macro default__safe_divide(numerator, denominator) -%}
    try_divide(cast({{ numerator }} as {{ float_type() }}), cast({{ denominator }} as {{ float_type() }}))
{%- endmacro %}

{% macro bigquery__safe_divide(numerator, denominator) -%}
    safe_divide(cast({{ numerator }} as {{ float_type() }}), cast({{ denominator }} as {{ float_type() }}))
{%- endmacro %}
