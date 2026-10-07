# Project 2: BigQuery + Trino, with Spark on a shared lakehouse (dbt v1)

> **Project 2 of 2** in this repository. Its peer is
> [`../1_dbt_bigquery_duckdb/`](../1_dbt_bigquery_duckdb/) (BigQuery + DuckDB, dbt v2).
> Both build **the same 30 models and 168 tests from the same source dataset**; the
> comparison is in [`../README.md`](../README.md) and
> [`../docs/comparison.md`](../docs/comparison.md). Run every command below from this folder.

One dbt project, two targets:

- **`bigquery`**: the cloud warehouse, reading `bigquery-public-data.thelook_ecommerce`.
- **`trino`**: Trino over an **Iceberg lakehouse that Spark shares**. dbt only ever talks
  to Trino. Spark produces the raw tables upstream and consumes dbt's marts downstream,
  through the same Iceberg catalog and object store.

It is **dbt v1 (dbt-core 1.11 + dbt-trino 1.10)** because dbt v2 (Fusion) has no Trino
adapter.

## Status (measured 2026-10-07)

| What | Result |
|---|---|
| `dbt build --target trino` | **198 / 198 ok** (30 models, 168 data tests), ~65 s |
| Model SQL shared with project 1 | **34 / 34 `.sql` files byte-identical**, 4 / 4 `.yml` files structurally equal (`../scripts/check_model_trees.py`) |
| Portability guardrail | **PORTABLE**: 0 / 19 BigQuery-only tokens in the Trino render, 0 / 18 Trino-only tokens in the BigQuery render, 0 target branches in models |
| Macros executed on Trino | **59 / 59** self-check cases ok (`make selfcheck`) |
| Spark reads what dbt built | **12 / 12 tables read by Spark with identical per-column profiles**; 0 / 18 views readable (by design, see below) |
| `bigquery` target | **197 pass, 1 warn, 0 error** on the real dataset, 152 s (`make bq`; the warning is the deliberate dirty-data test). Compiles with no credential in CI |
| Trino on the **real** data | **197 pass, 1 warn, 0 error**, 47 s, on the 3.3M real rows landed by Spark (`make trino-real`) |
| BigQuery vs Trino values | **30 / 30 relations identical** (887 / 887 per-column metrics), money exact to 9 decimals (`make parity`, [`docs/value_parity.md`](docs/value_parity.md)) |
| CI | `.github/workflows/2_dbt_bigquery_trino_spark.yml` runs `make pre-pr` end to end on every PR: green on GitHub's runner in 3m30s (first run, PR #33) |

## The architecture, and why it looks like this

```
                    ┌────────────────────────── one Iceberg lakehouse ──────────────────────────┐
                    │                                                                           │
  Spark job ──writes──▶ lake.thelook_ecommerce.*  ──source()──▶  dbt on Trino  ──writes──▶ lake.analytics_*.*  ──reads──▶ Spark job
  (upstream:        │   (Iceberg tables)                    (dbt-trino)            (Iceberg tables)          (downstream:
   land_sources.py) │                                                                                         profile_relations.py)
                    │       both engines resolve names in ONE Iceberg REST catalog                            │
                    │       and read/write the SAME Parquet files in ONE S3 bucket                           │
                    └───────────────────────────────────────────────────────────────────────────┘
```

**Trino does not send queries to Spark.** No Trino connector pushes SQL to a Spark
engine. In practice, Trino "reaches" Spark by sharing **tables**: both engines use the
same Iceberg catalog over the same object store. So Trino can join a table Spark
committed a minute ago with any other catalog it knows, and Spark can read every mart
dbt built. The research behind this choice, and the alternatives considered (Spark
Thrift Server, Hive Metastore vs REST catalog, Trino's BigQuery connector), are in
[`docs/architecture.md`](docs/architecture.md).

The local stack ([`stack/compose.yml`](stack/compose.yml)) is the smallest faithful
version of that architecture:

| Service | Image | Role |
|---|---|---|
| `storage` | SeaweedFS 4.48 | S3-compatible object store (MinIO stopped publishing community images in 2025) |
| `iceberg-rest` | `apache/iceberg-rest-fixture:1.10.0` | The Iceberg REST catalog both engines share |
| `trino` | `trinodb/trino:483` | The engine dbt talks to; catalog `lake` = the REST catalog |
| `spark` | `apache/spark:4.0.1` + Iceberg 1.10.0 | On-demand jobs (`docker compose run`), not a server |

## How to write models so this works

These rules come from failures measured while building this project. Each one is
enforced by a check, not just written down.

1. **Never name an engine in a model.** Every dialect difference goes through
   `macros/polyglot/`, which has a `bigquery__` and a `trino__` implementation for every
   macro (29 each). Enforced by `scripts/check_portability.py`.
2. **Never hard-code a catalog or schema.** Use `source()` and `ref()` only. The one
   target-dependent line in the project is the source `database:` in
   `models/staging/_thelook__sources.yml`, the same line as in project 1.
3. **What Spark reads must be a TABLE, never a view.** A Trino view is stored in the
   Iceberg catalog as Trino SQL. Spark cannot read any dbt-built view: dbt-trino quotes
   identifiers as `"lake"."schema"."table"`, which Spark does not parse. Even a
   hand-written view only works when its SQL happens to also be Spark SQL. When it is,
   Spark *re-executes* it with Spark semantics (measured: `7/2` is `3` on Trino and
   `3.5` on Spark). Marts are tables (`dbt_project.yml`). Enforced by
   `scripts/spark_interop.py`, which fails when any table is unreadable or differs.
4. **Only use types Iceberg can store**, because every Trino table here is an Iceberg
   table: no JSON, no geospatial, no `TIME WITH TIME ZONE`. Use `timestamp(6)` (Trino's
   bare `timestamp` is milliseconds), and keep decimals at 38 digits or fewer. The type
   macros encode all of this.
5. **Every table carries `read.parquet.vectorization.enabled=false`.** Trino writes
   Parquet v2 encodings that Iceberg's vectorized Spark reader cannot decode.
   Measured: Spark failed on 5 of the 12 tables without the property
   ([apache/iceberg#7162](https://github.com/apache/iceberg/issues/7162)). Set
   project-wide in `dbt_project.yml`.
6. **Pick physical layout per engine.** Iceberg partitions by `month(created_at)` where
   BigQuery partitions by day. Day partitioning hit Trino's 100-open-writers limit and
   would create hundreds of tiny files (`macros/polyglot/physical.sql`).

The full list of what was hit is in [`docs/challenges.md`](docs/challenges.md).

## Money: the gap project 1 has, closed here by design

Project 1's main measured value gap is money. DuckDB's `decimal(18,2)` rounds sub-cent
source values that BigQuery's `NUMERIC` (decimal(38,9)) keeps. Trino, Iceberg and Spark
can all hold **exactly** `decimal(38,9)`, so `money_type()` renders `decimal(38,9)` on
Trino. The self-check proves the sub-cent digits survive
(`6.644999999552965` → `6.645000000`). Measured end to end on the real data, it **does
close the gap**: every money sum is equal on BigQuery and Trino to the ninth decimal
place, in all 30 relations ([`docs/value_parity.md`](docs/value_parity.md)).

## Quickstart

Prerequisites: Docker with the compose plugin, `uv`, `openssl`. About 6 GB of images.

```bash
make setup        # uv sync + the Spark Iceberg jars (sha256-checked)
make stack-up     # S3 + Iceberg REST catalog + Trino, waits until healthy
make trino        # render the shared fixture, Spark lands it, dbt build --target trino
make interop      # Spark reads every relation dbt built, profiles compared with Trino
make pre-pr       # everything CI runs, in one command
make stack-reset  # stop the stack and delete its data
```

Trino's UI is at <http://localhost:8080>. To query the lakehouse directly, run
`docker compose -f stack/compose.yml exec trino trino`. To use Spark SQL on the same
tables:
`docker compose -f stack/compose.yml run --rm --entrypoint /opt/spark/bin/spark-sql spark`.

For the BigQuery target: `BQ_KEYFILE=/path/to/key.json make bq` (it writes to the
dataset `trino_experiments_${DBT_ENV:-dev}`, separate from project 1's). `BQ_PROJECT`
picks the GCP project (default `coreychimpbot`). To compare the two targets on the same
real rows: `make bq trino-real parity` ([`docs/value_parity.md`](docs/value_parity.md)).

## Repository map

| Path | Purpose |
|---|---|
| `models/`, `tests/` | The shared model tree: identical to project 1's (checked) |
| `macros/polyglot/` | The seam: one `bigquery__` and one `trino__` per macro, with the reason for each difference |
| `macros/polyglot/self_check.sql` | `polyglot_selfcheck` (executes every Trino rendering) and `polyglot_render` |
| `stack/compose.yml` | The local lakehouse: SeaweedFS, Iceberg REST, Trino, Spark |
| `stack/trino/catalog/lake.properties` | Trino's view of the lakehouse |
| `stack/spark/conf/spark-defaults.conf` | Spark's view of the same lakehouse |
| `stack/spark/jobs/land_sources.py` | Spark as the upstream producer of the raw tables |
| `stack/spark/jobs/profile_relations.py` | Spark as the downstream consumer of dbt's output |
| `scripts/render_fixture.py` | Renders project 1's fixture SQL to Parquet (the shared source rows) |
| `scripts/check_portability.py` | The guardrail: both targets compile, no dialect leak, no target branch |
| `scripts/spark_interop.py` | Spark vs Trino, every relation, every column |
| `scripts/pre_pr.sh` | `make pre-pr`, the routine CI runs |
| [`docs/architecture.md`](docs/architecture.md) | How Trino and Spark work together, options considered |
| [`docs/challenges.md`](docs/challenges.md) | Everything that was hit, measured, and how it was resolved |
| [`docs/gaps.md`](docs/gaps.md) | What is not verified yet, and blind spots |
| [`docs/value_parity.md`](docs/value_parity.md) | BigQuery vs Trino on the same real rows: how it was run, and the result |
| `scripts/render_real.py`, `scripts/bq_trino_parity.py` | Download the real sources for the Trino leg; compare the two targets |
