{#
  to_json_value(expr): a value (typically a struct) as JSON.

  BigQuery TO_JSON(<expr>) returns the JSON type. Trino has no TO_JSON; the cast
  `cast(<row> as json)` turns a named ROW into a JSON object. But Iceberg has NO JSON
  type, so a Trino table cannot store a JSON column at all: the Trino branch serialises
  it with JSON_FORMAT and stores VARCHAR. The column is therefore `json` on BigQuery and
  `varchar` (text holding JSON) on Trino and Spark. See docs/challenges.md.
#}
{% macro to_json_value(expr) -%}
    {{ return(adapter.dispatch('to_json_value', 'bq_trino_experiments')(expr)) }}
{%- endmacro %}

{% macro trino__to_json_value(expr) -%}
    json_format(cast({{ expr }} as json))
{%- endmacro %}

{% macro bigquery__to_json_value(expr) -%}
    to_json({{ expr }})
{%- endmacro %}
