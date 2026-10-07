{#
  to_json_value(expr): a value (typically a struct) as JSON. BigQuery and DuckDB
  both spell it TO_JSON(<expr>) with the same meaning, so the two branches are
  identical. It is a macro, unlike unnest(), only because the peer project
  (2_dbt_bigquery_trino_spark) shares this model tree and Trino has no TO_JSON:
  there it renders json_format(cast(<expr> as json)). Keep the shape so the
  shared models stay byte-identical.
#}
{% macro to_json_value(expr) -%}
    {{ return(adapter.dispatch('to_json_value', 'bq_duckdb_experiments')(expr)) }}
{%- endmacro %}

{% macro default__to_json_value(expr) -%}
    to_json({{ expr }})
{%- endmacro %}

{% macro bigquery__to_json_value(expr) -%}
    to_json({{ expr }})
{%- endmacro %}
