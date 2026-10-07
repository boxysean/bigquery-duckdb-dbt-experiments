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
  mart_customer_summary.average_order_value), do not use this macro: use
  money_quotient() below.
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

{#
  money_quotient(n, d): money divided by a count, at money precision, with BigQuery's
  semantics on every target: NUMERIC / INT64 is NUMERIC, the quotient rounded to nine
  decimals half away from zero, and NULL when d is 0. Use it for money per order
  (mart_daily_revenue.average_order_value, mart_customer_summary.average_order_value),
  as `round(money_quotient(x, y), 2)` cast to money_type().

  DuckDB divides every DECIMAL in DOUBLE, which cannot hold a half-way quotient exactly:
  191.249999999 / 2 = 95.6249999995 lands on either side of the cent once rounded (the
  rows that differed from BigQuery, docs/challenges.md 10.4; 102 of 5,000 random half-way
  cases were wrong through DOUBLE). So the DuckDB branch divides in integers: the
  numerator as nanos in a HUGEINT, rounded half away from zero, which is exact.
#}
{% macro money_quotient(numerator, denominator) -%}
    {{ return(adapter.dispatch('money_quotient', 'bq_duckdb_experiments')(numerator, denominator)) }}
{%- endmacro %}

{% macro default__money_quotient(numerator, denominator) -%}
    (case when {{ denominator }} = 0 then null else
        cast(sign(cast({{ numerator }} as decimal(38,9)))
             * ((2 * abs(cast(cast({{ numerator }} as decimal(38,9)) * 1000000000 as hugeint))
                 + abs({{ denominator }})) // (2 * abs({{ denominator }})))
             * sign({{ denominator }}) as decimal(38,0)) * cast(0.000000001 as decimal(38,9))
    end)
{%- endmacro %}

{% macro bigquery__money_quotient(numerator, denominator) -%}
    {{ numerator }} / nullif({{ denominator }}, 0)
{%- endmacro %}
