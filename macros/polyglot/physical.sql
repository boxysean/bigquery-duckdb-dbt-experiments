{#
  Physical layout. The cross-target seam for how a table is stored, not what it
  holds: a model splats `{{ config(**physical_layout()) }}` and gets whatever
  storage keys the running engine understands, without `models/` ever naming them.
#}

{#
  physical_layout(): the config keys for partitioning and clustering, returned as a
  dict for the model's config() call. BigQuery prices a query by the bytes it scans,
  so it partitions by day on created_at (a filter on created_at prunes whole
  partitions) and clusters by product_id (a filter on product_id reads fewer blocks
  inside each partition). DuckDB has no partition_by or cluster_by config at all, and
  a local columnar file has no per-byte bill to cut, so the default is an empty dict:
  the table is a plain table, and no key appears that the engine would not know.
#}
{% macro physical_layout() -%}
    {{ return(adapter.dispatch('physical_layout', 'bq_duckdb_experiments')()) }}
{%- endmacro %}

{% macro default__physical_layout() -%}
    {{ return({}) }}
{%- endmacro %}

{% macro bigquery__physical_layout() -%}
    {{ return({
        'partition_by': {'field': 'created_at', 'data_type': 'timestamp', 'granularity': 'day'},
        'cluster_by': ['product_id']
    }) }}
{%- endmacro %}
