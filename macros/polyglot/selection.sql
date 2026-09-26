{#
  except_columns(cols): `select *` minus the named columns. Both engines have the
  star modifier but name it differently: BigQuery writes `* EXCEPT (a, b)`,
  DuckDB writes `* EXCLUDE (a, b)` (DuckDB does not accept EXCEPT here, and
  BigQuery has no EXCLUDE). An empty list is a compiler error: `* except ()` is
  a syntax error on both engines.
  Usage: select {{ except_columns(['b', 'c']) }} from ...
#}
{% macro except_columns(cols) -%}
    {%- if cols is string or cols is not iterable or cols | length == 0 -%}
        {{ exceptions.raise_compiler_error(
            "except_columns(cols): cols must be a non-empty list of column names, got " ~ cols) }}
    {%- endif -%}
    {{ return(adapter.dispatch('except_columns', 'bq_duckdb_experiments')(cols)) }}
{%- endmacro %}

{% macro default__except_columns(cols) -%}
    * exclude ({{ cols | join(', ') }})
{%- endmacro %}

{% macro bigquery__except_columns(cols) -%}
    * except ({{ cols | join(', ') }})
{%- endmacro %}
