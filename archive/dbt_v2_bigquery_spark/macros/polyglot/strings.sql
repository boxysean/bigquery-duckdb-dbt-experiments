{#
  regexp_contains(expr, pattern): true when pattern matches anywhere in expr.
  BigQuery REGEXP_CONTAINS(<expr>, <pattern>); Spark REGEXP_LIKE(<expr>,
  <pattern>) (also spelt `<expr> RLIKE <pattern>`), with the same partial-match
  semantics (measured on Spark: 'LifeOS' matches '^Life' and 'OS', not '^Nope').
  The regex ENGINES differ: BigQuery uses RE2, Spark uses java.util.regex. The
  common subset (anchors, classes, quantifiers, alternation) agrees; Java-only
  features such as backreferences and lookaround are refused by RE2, so keep
  patterns to the common subset. pattern is a SQL expression, so quote a
  literal: {{ regexp_contains('email', "'@example\\.com$'") }}.
#}
{% macro regexp_contains(expr, pattern) -%}
    {{ return(adapter.dispatch('regexp_contains', 'bq_spark_experiments')(expr, pattern)) }}
{%- endmacro %}

{% macro default__regexp_contains(expr, pattern) -%}
    regexp_like({{ expr }}, {{ pattern }})
{%- endmacro %}

{% macro bigquery__regexp_contains(expr, pattern) -%}
    regexp_contains({{ expr }}, {{ pattern }})
{%- endmacro %}
