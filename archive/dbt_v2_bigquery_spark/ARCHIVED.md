# Archived: the dbt v2 BigQuery + Spark experiment

This folder was the repository's first attempt at a second engine: **one dbt v2 (dbt-oss
2.0.5 / Fusion) project targeting BigQuery and Spark directly**, with dbt talking to a Spark
Thrift Server. It ran end to end (29 models, 167 tests, value parity measured on real data;
see `docs/conclusion.md` and `docs/bigquery-to-spark.md`).

It was archived on 2026-10-07 when the comparison was re-scoped to:

1. `../../1_dbt_bigquery_duckdb/`: BigQuery + DuckDB on dbt v2 (unchanged), and
2. `../../2_dbt_bigquery_trino_spark/`: BigQuery + **Trino** on **dbt v1 (dbt-core)**,
   with Spark sharing the lakehouse through Iceberg tables. dbt v2 has no Trino adapter,
   and dbt never talks to Spark directly there.

It is kept, not deleted, because its Spark SQL findings (week truncation, decimal(38) ceiling,
`unnest`, 0- vs 1-based arrays, time zones) still apply to Spark as the consumer of
project 2's tables. It is **not maintained and not in CI**. Its dbt binary paths were
repointed at `1_dbt_bigquery_duckdb/.venv` so it can still be run by hand.
