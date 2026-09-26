{#
  Type names. The cross-target seam for DDL-ish spellings: a model casts to
  `{{ int_type() }}` and gets a type that exists on whichever engine is running.
  Money is fixed-point so sums do not drift; floats are for rates, ratios and
  coordinates only.
#}

{#
  int_type(): the 64-bit integer. BigQuery has exactly one integer type and
  spells it INT64; DuckDB's canonical 64-bit integer is the SQL-standard BIGINT
  (DuckDB happens to accept INT64 as an alias, but BigQuery rejects BIGINT, so
  the macro renders each engine's own name).
#}
{% macro int_type() -%}
    {{ return(adapter.dispatch('int_type', 'bq_duckdb_experiments')()) }}
{%- endmacro %}

{% macro default__int_type() -%}
    bigint
{%- endmacro %}

{% macro bigquery__int_type() -%}
    int64
{%- endmacro %}

{#
  string_type(): variable-length text. DuckDB keeps the SQL-standard VARCHAR;
  BigQuery has no VARCHAR and spells it STRING.
#}
{% macro string_type() -%}
    {{ return(adapter.dispatch('string_type', 'bq_duckdb_experiments')()) }}
{%- endmacro %}

{% macro default__string_type() -%}
    varchar
{%- endmacro %}

{% macro bigquery__string_type() -%}
    string
{%- endmacro %}

{#
  float_type(): IEEE 754 double precision. DuckDB spells it DOUBLE; BigQuery's
  only floating-point type is FLOAT64, and DuckDB rejects FLOAT64 as a type name.
#}
{% macro float_type() -%}
    {{ return(adapter.dispatch('float_type', 'bq_duckdb_experiments')()) }}
{%- endmacro %}

{% macro default__float_type() -%}
    double
{%- endmacro %}

{% macro bigquery__float_type() -%}
    float64
{%- endmacro %}

{#
  timestamp_type(): a naive timestamp. Every *_at column from staging up is this
  type, in UTC. The NAME is the same on both engines (TIMESTAMP) but the MEANING
  is not: BigQuery TIMESTAMP is an absolute instant, DuckDB TIMESTAMP is a
  wall-clock value with no zone. `to_utc_timestamp()` is what makes the two agree.
#}
{% macro timestamp_type() -%}
    {{ return(adapter.dispatch('timestamp_type', 'bq_duckdb_experiments')()) }}
{%- endmacro %}

{% macro default__timestamp_type() -%}
    timestamp
{%- endmacro %}

{% macro bigquery__timestamp_type() -%}
    timestamp
{%- endmacro %}

{#
  money_type(): fixed-point money (USD). BigQuery NUMERIC is always 38,9 and takes
  no parameters in an expression cast; DuckDB's DECIMAL needs an explicit
  width/scale (a bare DECIMAL is 18,3), so it is pinned to decimal(18,2).
#}
{% macro money_type() -%}
    {{ return(adapter.dispatch('money_type', 'bq_duckdb_experiments')()) }}
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
  DuckDB DECIMAL(p,s) tops out at p = 38 and rejects anything wider
  ("DECIMAL type width must be between 1 and 38"); BigQuery has NUMERIC
  (38 digits, scale 9) and BIGNUMERIC (76.76 digits, scale 38), and no DuckDB
  type is equivalent to BIGNUMERIC. The rule:

    * p <= 38: DuckDB `decimal(p, s)`; BigQuery `numeric` when s <= 9, else
      `bignumeric`.
    * p > 38:  BigQuery `bignumeric`; DuckDB raises a compiler error. It never
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
    {{ return(adapter.dispatch('decimal_type', 'bq_duckdb_experiments')(p, s)) }}
{%- endmacro %}

{% macro default__decimal_type(p, s) -%}
    {%- if p > 38 -%}
        {{ exceptions.raise_compiler_error(
            "decimal_type(" ~ p ~ ", " ~ s ~ "): DuckDB DECIMAL is capped at 38 digits of precision "
            ~ "(BigQuery would render BIGNUMERIC, which has no DuckDB equivalent). Either declare a "
            ~ "narrower decimal (p <= 38), or use float_type() and accept 15-16 significant digits. "
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
  type_bigint_array(): an array of 64-bit integers. DuckDB writes arrays with the
  `T[]` suffix (`bigint[]`); BigQuery uses the parameterised `ARRAY<T>` type
  (`array<int64>`), which DuckDB does not parse.
#}
{% macro type_bigint_array() -%}
    {{ return(adapter.dispatch('type_bigint_array', 'bq_duckdb_experiments')()) }}
{%- endmacro %}

{% macro default__type_bigint_array() -%}
    bigint[]
{%- endmacro %}

{% macro bigquery__type_bigint_array() -%}
    array<int64>
{%- endmacro %}
