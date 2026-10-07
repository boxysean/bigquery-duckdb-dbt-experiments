{#
  regexp_contains(expr, pattern): true when pattern matches anywhere in expr.
  Both engines use RE2 with the same partial-match semantics; only the name
  differs: BigQuery REGEXP_CONTAINS(<expr>, <pattern>), DuckDB
  REGEXP_MATCHES(<expr>, <pattern>). pattern is a SQL expression, so quote a
  literal: {{ regexp_contains('email', "'@example\\.com$'") }}.
#}
{% macro regexp_contains(expr, pattern) -%}
    {{ return(adapter.dispatch('regexp_contains', 'bq_duckdb_experiments')(expr, pattern)) }}
{%- endmacro %}

{% macro default__regexp_contains(expr, pattern) -%}
    regexp_matches({{ expr }}, {{ pattern }})
{%- endmacro %}

{% macro bigquery__regexp_contains(expr, pattern) -%}
    regexp_contains({{ expr }}, {{ pattern }})
{%- endmacro %}
