{#
  except_columns(cols): `select *` minus the named columns.

  BigQuery writes `* EXCEPT (a, b)`. Trino has NO star modifier of any kind (no EXCEPT,
  no EXCLUDE, no REPLACE), so there is nothing to render: the Trino branch is a compiler
  error, and the only portable form is to list the columns you want. No model uses
  this macro (the same is true in project 1); it is kept so the seam has the same shape
  in both projects and so the gap fails loudly instead of silently. See
  docs/challenges.md.
#}
{% macro except_columns(cols) -%}
    {%- if cols is string or cols is not iterable or cols | length == 0 -%}
        {{ exceptions.raise_compiler_error(
            "except_columns(cols): cols must be a non-empty list of column names, got " ~ cols) }}
    {%- endif -%}
    {{ return(adapter.dispatch('except_columns', 'bq_trino_experiments')(cols)) }}
{%- endmacro %}

{% macro trino__except_columns(cols) -%}
    {{ exceptions.raise_compiler_error(
        "except_columns(" ~ cols ~ "): Trino has no `select * except/exclude (...)`. "
        ~ "List the columns explicitly; there is no portable star modifier on Trino.") }}
{%- endmacro %}

{% macro bigquery__except_columns(cols) -%}
    * except ({{ cols | join(', ') }})
{%- endmacro %}
