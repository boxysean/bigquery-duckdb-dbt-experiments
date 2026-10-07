{#
  Type names: the seam for DDL-ish spellings. A model casts to `{{ int_type() }}` and
  gets a type that exists on whichever engine is running.

  Every type rendered on Trino must also be a type ICEBERG can store, because every
  Trino table here is an Iceberg table that Spark reads. That rules out Trino's JSON,
  TIME WITH TIME ZONE, VARCHAR(n) (stored as plain varchar), TINYINT/SMALLINT (widened)
  and the geospatial types. See docs/challenges.md "Iceberg is the type system".
#}

{#
  int_type(): the 64-bit integer. BigQuery INT64; Trino BIGINT (Iceberg long, Spark
  BIGINT). Trino's INTEGER is 32-bit, so a bare `cast(x as integer)` would be narrower
  than BigQuery's only integer.
#}
{% macro int_type() -%}
    {{ return(adapter.dispatch('int_type', 'bq_trino_experiments')()) }}
{%- endmacro %}

{% macro trino__int_type() -%}
    bigint
{%- endmacro %}

{% macro bigquery__int_type() -%}
    int64
{%- endmacro %}

{#
  string_type(): variable-length text. BigQuery STRING; Trino VARCHAR (unbounded).
#}
{% macro string_type() -%}
    {{ return(adapter.dispatch('string_type', 'bq_trino_experiments')()) }}
{%- endmacro %}

{% macro trino__string_type() -%}
    varchar
{%- endmacro %}

{% macro bigquery__string_type() -%}
    string
{%- endmacro %}

{#
  float_type(): IEEE 754 double. BigQuery FLOAT64; Trino DOUBLE (Trino rejects FLOAT64).
#}
{% macro float_type() -%}
    {{ return(adapter.dispatch('float_type', 'bq_trino_experiments')()) }}
{%- endmacro %}

{% macro trino__float_type() -%}
    double
{%- endmacro %}

{% macro bigquery__float_type() -%}
    float64
{%- endmacro %}

{#
  timestamp_type(): a naive timestamp, in UTC (see to_utc_timestamp). Every *_at column
  from staging up is this type.

  Trino's bare TIMESTAMP is timestamp(3), MILLISECOND precision: a plain
  `cast(x as timestamp)` silently drops the microseconds BigQuery keeps. Iceberg stores
  microseconds, so the Trino branch pins timestamp(6) (Iceberg `timestamp`, read by
  Spark as TIMESTAMP_NTZ).
#}
{% macro timestamp_type() -%}
    {{ return(adapter.dispatch('timestamp_type', 'bq_trino_experiments')()) }}
{%- endmacro %}

{% macro trino__timestamp_type() -%}
    timestamp(6)
{%- endmacro %}

{% macro bigquery__timestamp_type() -%}
    timestamp
{%- endmacro %}

{#
  money_type(): fixed-point money (USD).

  BigQuery NUMERIC is always decimal(38,9). Trino (and Iceberg, and Spark) can hold
  EXACTLY that type, so the Trino branch renders decimal(38,9) and money keeps the same
  nine decimals on both targets. This is a deliberate difference from project 1, whose
  DuckDB leg uses decimal(18,2) and therefore rounds sub-cent source values that
  BigQuery keeps (project 1's main measured value gap). See docs/challenges.md.
#}
{% macro money_type() -%}
    {{ return(adapter.dispatch('money_type', 'bq_trino_experiments')()) }}
{%- endmacro %}

{% macro trino__money_type() -%}
    decimal(38,9)
{%- endmacro %}

{% macro bigquery__money_type() -%}
    numeric
{%- endmacro %}

{#
  decimal_type(p, s): a fixed-point decimal of precision p and scale s.
    * p <= 38: Trino `decimal(p,s)`; BigQuery `numeric` when s <= 9, else `bignumeric`.
    * p > 38:  BigQuery `bignumeric`; Trino raises a compiler error (Trino, Iceberg and
      Spark all stop at 38 digits). It never silently falls back to DOUBLE.
#}
{% macro decimal_type(p, s) -%}
    {%- if p is not number or s is not number or p < 1 or s < 0 or s > p -%}
        {{ exceptions.raise_compiler_error(
            "decimal_type(p, s): need integers with 1 <= p and 0 <= s <= p, got p=" ~ p ~ ", s=" ~ s) }}
    {%- endif -%}
    {{ return(adapter.dispatch('decimal_type', 'bq_trino_experiments')(p, s)) }}
{%- endmacro %}

{% macro trino__decimal_type(p, s) -%}
    {%- if p > 38 -%}
        {{ exceptions.raise_compiler_error(
            "decimal_type(" ~ p ~ ", " ~ s ~ "): Trino DECIMAL (and Iceberg, and Spark) is capped at "
            ~ "38 digits of precision (BigQuery would render BIGNUMERIC). Either declare a narrower "
            ~ "decimal (p <= 38), or use float_type() and accept 15-16 significant digits. "
            ~ "Refusing to fall back to DOUBLE silently.") }}
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
  type_bigint_array(): an array of 64-bit integers. BigQuery ARRAY<INT64>; Trino
  ARRAY(BIGINT), with parentheses (Trino does not parse the angle-bracket form).
#}
{% macro type_bigint_array() -%}
    {{ return(adapter.dispatch('type_bigint_array', 'bq_trino_experiments')()) }}
{%- endmacro %}

{% macro trino__type_bigint_array() -%}
    array(bigint)
{%- endmacro %}

{% macro bigquery__type_bigint_array() -%}
    array<int64>
{%- endmacro %}

{#
  geography_type(): a point in WGS84 lon/lat. BigQuery GEOGRAPHY. Trino has
  SphericalGeography, but it is an in-memory type: Iceberg cannot store it (and Spark
  has no geography type either), so on the lakehouse the value is WKT text and the
  Trino branch renders VARCHAR. Use ST_GeometryFromText(...) at query time if needed.
  No model reads these columns today.
#}
{% macro geography_type() -%}
    {{ return(adapter.dispatch('geography_type', 'bq_trino_experiments')()) }}
{%- endmacro %}

{% macro trino__geography_type() -%}
    varchar
{%- endmacro %}

{% macro bigquery__geography_type() -%}
    geography
{%- endmacro %}
