{#
  The cross-target seam.

  Sean's plan: "one single project power both with using macros to help transpile."
  That means dialect differences live HERE, not in a forked model tree. Every
  macro below is dispatched on the adapter (bigquery, duckdb), so a model can
  call `string_type()` and get a type that exists on whichever engine is running.

  These two macros are deliberately small: this card ships an empty skeleton, and
  a macro nobody calls is dead code. They exist to prove the seam works end to end
  (`dbt run-operation to_string --target duckdb`) and to set the shape the real
  macros in later cards should follow.
#}

{% macro string_type() -%}
    {{ return(adapter.dispatch('string_type', 'bq_duckdb_experiments')()) }}
{%- endmacro %}

{# Fallback for any adapter (DuckDB lands here; so does anything added later). #}
{% macro default__string_type() -%}
    varchar
{%- endmacro %}

{# BigQuery spells it `STRING`. #}
{% macro bigquery__string_type() -%}
    string
{%- endmacro %}

{# Usage shape a model would have: {{ to_string('my_column') }} #}
{% macro to_string(column_name) -%}
    cast({{ column_name }} as {{ string_type() }})
{%- endmacro %}
