{#
  safe_divide(n, d): n / d, NULL when d is 0 (or NULL), always a double. BigQuery has
  SAFE_DIVIDE; Trino does not, so it uses NULLIF on the divisor. (Trino double division
  by zero does not raise, it returns Infinity or NaN, which is worse than an error:
  NULLIF is what makes the semantics equal.) Both sides are cast to float_type().
  Where a model wants DECIMAL rounding (money per order), do not use this macro: use
  money_quotient() below.
#}
{% macro safe_divide(numerator, denominator) -%}
    {{ return(adapter.dispatch('safe_divide', 'bq_trino_experiments')(numerator, denominator)) }}
{%- endmacro %}

{% macro trino__safe_divide(numerator, denominator) -%}
    cast({{ numerator }} as {{ float_type() }}) / nullif(cast({{ denominator }} as {{ float_type() }}), 0)
{%- endmacro %}

{% macro bigquery__safe_divide(numerator, denominator) -%}
    safe_divide(cast({{ numerator }} as {{ float_type() }}), cast({{ denominator }} as {{ float_type() }}))
{%- endmacro %}

{#
  money_quotient(n, d): money divided by a count, at money precision, with BigQuery's
  semantics on every target: NUMERIC / INT64 is NUMERIC, the quotient rounded to nine
  decimals half away from zero, and NULL when d is 0. Use it for money per order
  (mart_daily_revenue.average_order_value, mart_customer_summary.average_order_value),
  as `round(money_quotient(x, y), 2)` cast to money_type().

  Trino's decimal division is already that (decimal(38,9) / bigint is decimal(38,9),
  rounded half up), measured equal to BigQuery on every row of both models.
#}
{% macro money_quotient(numerator, denominator) -%}
    {{ return(adapter.dispatch('money_quotient', 'bq_trino_experiments')(numerator, denominator)) }}
{%- endmacro %}

{% macro trino__money_quotient(numerator, denominator) -%}
    {{ numerator }} / nullif({{ denominator }}, 0)
{%- endmacro %}

{% macro bigquery__money_quotient(numerator, denominator) -%}
    {{ numerator }} / nullif({{ denominator }}, 0)
{%- endmacro %}
