{#
  except_columns(cols): `select *` minus the named columns. The two engines
  AGREE here: BigQuery writes `* EXCEPT (a, b)`, and Spark 4.2 accepts the same
  spelling (measured on Spark 4.2.0: `select * except (b) from (select 1 as a,
  2 as b)` returns only `a`; the other common spelling, `* exclude (b)`, is a
  parse error on Spark). So both branches render `* except (...)`: the macro
  exists for symmetry, so the seam has one shape and a future engine that
  disagrees has a place to say so, not because these two engines diverge.
  An empty list is a compiler error: `* except ()` is a syntax error.
  Usage: select {{ except_columns(['b', 'c']) }} from ...
#}
{% macro except_columns(cols) -%}
    {%- if cols is string or cols is not iterable or cols | length == 0 -%}
        {{ exceptions.raise_compiler_error(
            "except_columns(cols): cols must be a non-empty list of column names, got " ~ cols) }}
    {%- endif -%}
    {{ return(adapter.dispatch('except_columns', 'bq_spark_experiments')(cols)) }}
{%- endmacro %}

{% macro default__except_columns(cols) -%}
    * except ({{ cols | join(', ') }})
{%- endmacro %}

{% macro bigquery__except_columns(cols) -%}
    * except ({{ cols | join(', ') }})
{%- endmacro %}
