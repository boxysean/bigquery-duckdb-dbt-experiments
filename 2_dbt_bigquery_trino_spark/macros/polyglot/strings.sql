{#
  regexp_contains(expr, pattern): true when pattern matches anywhere in expr. BigQuery
  REGEXP_CONTAINS (RE2); Trino REGEXP_LIKE (Java regex by default; Trino can be switched
  to RE2J with regex-library=RE2J). The two dialects agree on ordinary patterns
  (classes, anchors, alternation) and differ on look-around and backreferences, which
  RE2 does not support at all. Quote a literal pattern:
  {{ regexp_contains('email', "'@example\\.com$'") }}.
#}
{% macro regexp_contains(expr, pattern) -%}
    {{ return(adapter.dispatch('regexp_contains', 'bq_trino_experiments')(expr, pattern)) }}
{%- endmacro %}

{% macro trino__regexp_contains(expr, pattern) -%}
    regexp_like({{ expr }}, {{ pattern }})
{%- endmacro %}

{% macro bigquery__regexp_contains(expr, pattern) -%}
    regexp_contains({{ expr }}, {{ pattern }})
{%- endmacro %}
