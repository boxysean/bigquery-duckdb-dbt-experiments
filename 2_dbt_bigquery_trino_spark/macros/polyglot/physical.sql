{#
  physical_layout(): the config keys for how a table is stored, returned as a dict for
  the model's `{{ config(**physical_layout()) }}`.

  BigQuery partitions by day on created_at and clusters by product_id (it prices by
  bytes scanned). The Trino table is an Iceberg table, which has the same two ideas
  under different names: a hidden partition transform and a sort order `sorted_by`
  (data files are written sorted, so min/max statistics prune files on product_id).
  dbt-trino passes both through its `properties` config. Spark reads the same partition
  spec, so a Spark filter on created_at prunes too.

  The grain is MONTH on Iceberg, not BigQuery's day, on purpose. Measured: with
  `day(created_at)` the build fails with ICEBERG_TOO_MANY_OPEN_PARTITIONS ("Exceeded
  limit of 100 open writers for partitions: 177"), because a Trino writer keeps one file
  open per partition and stops at iceberg.max-partitions-per-writer (100). Raising that
  limit would "work", but every day becomes its own tiny Parquet file: on a lakehouse,
  per-file overhead (not bytes billed) is the cost, so a partition should hold far more
  rows than one day of this table does. BigQuery partitions are managed storage with no
  such overhead. The layout is a per-engine decision, which is exactly why it lives in
  this seam and not in the model.

  `extra_properties` repeats the project-wide Spark-readability property from
  dbt_project.yml, because a model-level `properties` dict replaces the project one.
#}
{% macro physical_layout() -%}
    {{ return(adapter.dispatch('physical_layout', 'bq_trino_experiments')()) }}
{%- endmacro %}

{% macro trino__physical_layout() -%}
    {{ return({
        'properties': {
            'extra_properties': "map(array['read.parquet.vectorization.enabled'], array['false'])",
            'partitioning': "ARRAY['month(created_at)']",
            'sorted_by': "ARRAY['product_id']"
        }
    }) }}
{%- endmacro %}

{% macro bigquery__physical_layout() -%}
    {{ return({
        'partition_by': {'field': 'created_at', 'data_type': 'timestamp', 'granularity': 'day'},
        'cluster_by': ['product_id']
    }) }}
{%- endmacro %}
