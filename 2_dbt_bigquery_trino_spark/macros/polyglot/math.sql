{#
  safe_divide(n, d): n / d, NULL when d is 0 (or NULL), always a double. BigQuery has
  SAFE_DIVIDE; Trino does not, so it uses NULLIF on the divisor. (Trino double division
  by zero does not raise, it returns Infinity or NaN, which is worse than an error:
  NULLIF is what makes the semantics equal.) Both sides are cast to float_type().
  Where a model wants DECIMAL rounding (money per order), do not use this macro: keep
  `round(x / nullif(y, 0), 2)` cast to money_type().
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
