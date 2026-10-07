{#
  Type names. The cross-target seam for DDL-ish spellings: a model casts to
  `{{ int_type() }}` and gets a type that exists on whichever engine is running.
  Money is fixed-point so sums do not drift; floats are for rates, ratios and
  coordinates only. Every Spark type name below was read back with typeof() on
  Spark 4.2.0.
#}

{#
  int_type(): the 64-bit integer. BigQuery has exactly one integer type and
  spells it INT64; Spark's 64-bit integer is BIGINT (typeof = bigint).
#}
{% macro int_type() -%}
    {{ return(adapter.dispatch('int_type', 'bq_spark_experiments')()) }}
{%- endmacro %}

{% macro default__int_type() -%}
    bigint
{%- endmacro %}

{% macro bigquery__int_type() -%}
    int64
{%- endmacro %}

{#
  string_type(): variable-length text. Both engines spell it STRING (Spark has
  no unbounded VARCHAR; typeof = string). The dispatch is kept so the seam has
  one shape.
#}
{% macro string_type() -%}
    {{ return(adapter.dispatch('string_type', 'bq_spark_experiments')()) }}
{%- endmacro %}

{% macro default__string_type() -%}
    string
{%- endmacro %}

{% macro bigquery__string_type() -%}
    string
{%- endmacro %}

{#
  float_type(): IEEE 754 double precision. Spark spells it DOUBLE (typeof =
  double); BigQuery's only floating-point type is FLOAT64.
#}
{% macro float_type() -%}
    {{ return(adapter.dispatch('float_type', 'bq_spark_experiments')()) }}
{%- endmacro %}

{% macro default__float_type() -%}
    double
{%- endmacro %}

{% macro bigquery__float_type() -%}
    float64
{%- endmacro %}

{#
  timestamp_type(): every *_at column from staging up is this type, in UTC.
  The name is TIMESTAMP on both engines, and so is the meaning, with one
  condition: a BigQuery TIMESTAMP is an absolute instant; a Spark TIMESTAMP is
  an instant too (TIMESTAMP_LTZ, not TIMESTAMP_NTZ), but it renders, truncates
  and converts to DATE in the session time zone. The Spark session is pinned to
  UTC (see to_utc_timestamp and the self-check), which is what makes the two
  agree.
#}
{% macro timestamp_type() -%}
    {{ return(adapter.dispatch('timestamp_type', 'bq_spark_experiments')()) }}
{%- endmacro %}

{% macro default__timestamp_type() -%}
    timestamp
{%- endmacro %}

{% macro bigquery__timestamp_type() -%}
    timestamp
{%- endmacro %}

{#
  money_type(): fixed-point money (USD). BigQuery NUMERIC is always 38,9 and takes
  no parameters in an expression cast; Spark's DECIMAL needs an explicit
  width/scale (a bare DECIMAL is decimal(10,0)), so it is pinned to
  decimal(18,2). Spark DECIMAL is exact to its declared scale, so a sum of
  values rounded to cents on Spark can differ from BigQuery's nine-decimal
  NUMERIC: that prediction is measured by the parity report, not assumed.
#}
{% macro money_type() -%}
    {{ return(adapter.dispatch('money_type', 'bq_spark_experiments')()) }}
{%- endmacro %}

{% macro default__money_type() -%}
    decimal(18,2)
{%- endmacro %}

{% macro bigquery__money_type() -%}
    numeric
{%- endmacro %}

{#
  decimal_type(p, s): a fixed-point decimal of precision p (total digits) and
  scale s (fractional digits). The two engines have different ceilings:
  Spark DECIMAL(p,s) tops out at p = 38 (measured on Spark 4.2.0:
  `cast(1 as decimal(39,2))` fails with DECIMAL_PRECISION_EXCEEDS_MAX_PRECISION
  "Decimal precision 39 exceeds max precision 38"); BigQuery has NUMERIC
  (38 digits, scale 9) and BIGNUMERIC (76.76 digits, scale 38), and no Spark
  type is equivalent to BIGNUMERIC. The rule:

    * p <= 38: Spark `decimal(p,s)`; BigQuery `numeric` when s <= 9, else
      `bignumeric`.
    * p > 38:  BigQuery `bignumeric`; Spark raises a compiler error. It never
      silently falls back to DOUBLE: a silent float is the failure this rule
      exists to prevent. The two legal ways out are to declare a narrower
      decimal (p <= 38) or to use float_type() and accept 15-16 significant
      digits.
#}
{% macro decimal_type(p, s) -%}
    {%- if p is not number or s is not number or p < 1 or s < 0 or s > p -%}
        {{ exceptions.raise_compiler_error(
            "decimal_type(p, s): need integers with 1 <= p and 0 <= s <= p, got p=" ~ p ~ ", s=" ~ s) }}
    {%- endif -%}
    {{ return(adapter.dispatch('decimal_type', 'bq_spark_experiments')(p, s)) }}
{%- endmacro %}

{% macro default__decimal_type(p, s) -%}
    {%- if p > 38 -%}
        {{ exceptions.raise_compiler_error(
            "decimal_type(" ~ p ~ ", " ~ s ~ "): Spark DECIMAL is capped at precision 38 "
            ~ "(DECIMAL_PRECISION_EXCEEDS_MAX_PRECISION above it), while BigQuery reaches "
            ~ "BIGNUMERIC at 76.76 digits of precision (scale 38), which has no Spark equivalent. "
            ~ "Either declare a narrower decimal (p <= 38), or use float_type() and accept 15-16 "
            ~ "significant digits. Refusing to fall back to DOUBLE silently.") }}
    {%- endif -%}
    decimal({{ p }},{{ s }})
{%- endmacro %}

{% macro bigquery__decimal_type(p, s) -%}
    {%- if p <= 38 and s <= 9 -%}
        numeric
    {%- else -%}
        bignumeric
    {%- endif -%}
{%- endmacro %}

{#
  type_bigint_array(): an array of 64-bit integers. Both engines use the
  parameterised ARRAY<T> form, with their own element name: Spark
  `array<bigint>` (typeof = array<bigint>), BigQuery `array<int64>`.
  Note: dbt-oss 2.0.5's spark adapter cannot FETCH an array column
  ("NotImplemented: [spark] Unsupported type ARRAY_TYPE"), so an array may live
  inside a model but not in a result set returned to dbt (dbt show, run_query).
#}
{% macro type_bigint_array() -%}
    {{ return(adapter.dispatch('type_bigint_array', 'bq_spark_experiments')()) }}
{%- endmacro %}

{% macro default__type_bigint_array() -%}
    array<bigint>
{%- endmacro %}

{% macro bigquery__type_bigint_array() -%}
    array<int64>
{%- endmacro %}
