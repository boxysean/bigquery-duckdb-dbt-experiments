# How Trino and Spark work together here, and why

*The research behind project 2's shape. The brief: "everything goes to Trino, and Trino
can federate queries to Spark; write the dbt models so that is possible." What follows is
what was found, what was chosen, and the measurements behind it (2026-10-07).*

## 1. Trino cannot send a query to Spark

Trino federates across **connectors**: each catalog is a connector to some storage or
database (Iceberg, Hive, Delta Lake, PostgreSQL, BigQuery, and so on). None of them is a
"Spark connector" that hands SQL to a Spark engine and streams results back. There is
also no generic JDBC or HiveServer2 connector that could point at a Spark Thrift Server.
The idea "Trino pushes this part of the plan down to Spark" has no implementation.

What does exist, and is how Trino and Spark share work in practice, is a **shared table
format and catalog**:

- Spark writes a table (Iceberg, Delta or Hive) and commits it to a catalog.
- Trino resolves the same name in the same catalog, reads the same metadata and files,
  and can join that table with anything else it can reach in **one query**. That is
  Trino's federation.
- The reverse works too: Trino (and so dbt-trino) writes tables that Spark reads.

So the brief is satisfied in the way that actually works: **everything goes to Trino;
Spark-produced data reaches Trino as tables, not as queries.** dbt never talks to Spark.

## 2. The choices made, and the alternatives

| Decision | Chosen | Alternatives considered | Why |
|---|---|---|---|
| dbt version | **dbt v1** (dbt-core 1.11.11, dbt-trino 1.10.2) | dbt v2 / Fusion | dbt v2 has no Trino adapter (its supported list is snowflake, bigquery, databricks, redshift, duckdb, salesforce, clickhouse, with spark only behind an experimental flag) |
| How dbt reaches Spark data | **Through Trino, via shared Iceberg tables** | dbt-spark as a second adapter; a Spark Thrift Server | dbt talks to one engine. A second adapter would be a second project or a third target, not "everything goes to Trino" |
| Table format | **Apache Iceberg** (format v2) | Delta Lake, Hive tables | First-class read/write in both engines, an open REST catalog spec, hidden partitioning, and Trino's best-supported write path |
| Catalog | **Iceberg REST catalog** (`apache/iceberg-rest-fixture` locally) | Hive Metastore; Nessie; Apache Polaris; Lakekeeper; Unity Catalog; AWS Glue | REST is the vendor-neutral spec every engine now speaks. Locally the reference fixture is one container with no database. In production, swap in Polaris, Lakekeeper, Glue, Unity, and so on; the engines' config changes, the models do not |
| Object store | **S3 API** (SeaweedFS locally) | Local filesystem | Production lakehouses are on S3 or GCS. Both engines' S3 clients are what is exercised. MinIO's community images are no longer published, so SeaweedFS stands in |
| Spark's role | **Upstream producer + downstream consumer**, as batch jobs | A long-running Spark Thrift Server | Matches how Spark is used beside Trino in practice (ingestion, ML, heavy batch). Nothing needs a Spark server |
| Where BigQuery fits | **The second dbt target**, as in project 1 | Trino's BigQuery connector as a source | See section 4 |

## 3. The round trip that runs on every PR

1. `scripts/render_fixture.py` runs **project 1's own fixture SQL** in DuckDB and writes
   the seven tables to Parquet. The source dataset is shared, not copied.
2. **Spark** (`stack/spark/jobs/land_sources.py`) writes them as Iceberg tables
   `lake.thelook_ecommerce.*`. Spark plays the upstream pipeline that owns raw data.
3. **dbt on Trino** reads them with `source('thelook_ecommerce', ...)` and builds 30
   models into `lake.analytics_<env>`: 18 views (staging, intermediate) and 12 Iceberg
   tables (marts). Then it runs the 168 tests.
4. **Spark** (`stack/spark/jobs/profile_relations.py`) reads every relation dbt built.
   `scripts/spark_interop.py` compares a per-column profile computed by each engine:
   counts, exact sums, distinct counts, timestamp ranges in microseconds, array sizes.

Measured result: **all 12 tables are read by Spark with identical profiles. None of the
18 views can be read by Spark.** The views result is acceptable by design, and section 5
explains why.

## 4. What about Trino's BigQuery connector?

Trino can read BigQuery directly (`connector.name=bigquery`), so in principle the
`trino` target could read the *real* `bigquery-public-data.thelook_ecommerce` instead of
a fixture landed by Spark. It was not made the default, for two reasons:

- It needs a GCP credential on every run, including CI. The local round trip needs none,
  which is what lets CI run the whole Trino leg on every PR for free.
- It changes what the comparison measures. Project 1's DuckDB leg reads the fixture by
  default. Reading the same fixture keeps the two projects comparable.

It is the natural way to run project 2 on the real data, and the obvious next step
([`gaps.md`](gaps.md)): add a `bigquery` catalog to Trino, then either land the real
tables into `lake.thelook_ecommerce` with one `INSERT ... SELECT` per table, or point the
source at that catalog. The models do not change in either case: the source `database:`
line already switches on the target.

## 5. Rules the models follow because of this architecture

These are the model-writing rules. Each one exists because something failed without it.

| Rule | What failed without it | Where it is enforced |
|---|---|---|
| No engine-specific SQL in models; everything through `macros/polyglot` | n/a (the rule that makes two targets possible at all) | `scripts/check_portability.py` |
| No hard-coded catalog or schema; `source()` / `ref()` only | The source catalog differs per target (`bigquery-public-data` vs `lake`) | Purity check in `check_portability.py` (one allow-listed line) |
| What Spark reads is a table, not a view | Spark cannot parse dbt-trino's views (`"lake"."schema"."t"` quoting): 18 of 18 unreadable. A view with Trino-only functions fails (`ROUTINE_NOT_FOUND`). A view whose SQL also parses as Spark SQL is **re-executed with Spark semantics** (`7/2` = 3 on Trino, 3.5 on Spark) | `scripts/spark_interop.py` gates tables |
| Iceberg-storable types only (`timestamp(6)`, decimal ≤ 38, no JSON or geospatial) | Trino `json` and `SphericalGeography` cannot be stored in Iceberg; Trino's bare `timestamp` is milliseconds | Type macros; self-check cases |
| Every table carries `read.parquet.vectorization.enabled=false` | Spark failed on 5 of 12 tables: Trino's Parquet v2 encodings vs Iceberg's vectorized reader | `dbt_project.yml`; interop gate |
| Physical layout chosen per engine (month on Iceberg, day on BigQuery) | `ICEBERG_TOO_MANY_OPEN_PARTITIONS` with daily partitions, plus the small-files problem | `physical_layout()` |

## 6. How the local stack maps to production

| Local | Production equivalent | What changes in this project |
|---|---|---|
| SeaweedFS | S3 / GCS / ADLS | `s3.endpoint` and credentials in `lake.properties` and `spark-defaults.conf` |
| `iceberg-rest-fixture` (SQLite) | Polaris, Lakekeeper, Glue, Unity, Nessie, Gravitino | Catalog URI and auth in the same two files |
| Single-node Trino | A Trino cluster or Starburst | `profiles.yml` host, port, auth |
| `spark-submit local[2]` | EMR, Dataproc, Databricks, Spark on Kubernetes | Spark catalog config (same keys) |
| dbt `trino` target | Same | Nothing |

The models, the macros and the checks do not change.

## Sources

- Apache Iceberg REST catalog spec and multi-engine use: [Gravitino: Trino via Iceberg REST](https://gravitino.apache.org/docs/next/iceberg-rest-engine/trino), [Lakekeeper: engines](https://docs.lakekeeper.io/docs/0.7.x/engines/), [Query one Iceberg table from Trino, Spark and DuckDB](https://dev.to/databasin/query-one-apache-iceberg-table-from-trino-spark-and-duckdb-5c1k).
- The vectorized-reader / Parquet v2 encoding incompatibility: [apache/iceberg#7162](https://github.com/apache/iceberg/issues/7162), [SPARK-36879](https://issues.apache.org/jira/browse/SPARK-36879).
- Everything else on this page was measured in this repository; the commands are in the
  project README and `scripts/pre_pr.sh`.
