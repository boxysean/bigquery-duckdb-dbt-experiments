# Comparison: building and maintaining option 2 vs option 1

*Option 1*: [`1_dbt_bigquery_duckdb`](../1_dbt_bigquery_duckdb/): BigQuery + DuckDB, dbt v2.
*Option 2*: [`2_dbt_bigquery_trino_spark`](../2_dbt_bigquery_trino_spark/): BigQuery + Trino
over an Iceberg lakehouse shared with Spark, dbt v1.

Both projects build **the same 30 models and 168 tests** from **the same source dataset**.
Every model `.sql` file is byte-identical across the two, enforced in CI by
`scripts/check_model_trees.py`. So the differences below come from the platform, not
from different models.

Status of this assessment (2026-10-07): **preliminary.** Option 1's BigQuery leg is built
and value-measured on real data. Option 2's BigQuery leg compiles but has not been built
yet (no credential in the session that built it; see option 2's
[`gaps.md`](../2_dbt_bigquery_trino_spark/docs/gaps.md)). Every number below is measured
unless marked otherwise.

## Side by side

| Dimension | Option 1: BigQuery + DuckDB | Option 2: BigQuery + Trino (+ Spark) |
|---|---|---|
| dbt | v2 (dbt-oss 2.0.5 / Fusion) | **v1** (dbt-core 1.11.11 + dbt-trino 1.10.2). dbt v2 has no Trino adapter |
| Shared model SQL | 34 `.sql` files (baseline) | **Same 34, byte-identical.** Porting needed **1 change to 1 model** (typed struct fields in `mart_polyglot_types`), made render-neutral for option 1 |
| Macro seam | 29 macros × 2 implementations, 812 lines | 29 macros × 2 implementations, 812 lines. **The same size** |
| Dialect strictness for model authors | BigQuery and DuckDB both infer struct field types; both have a star modifier | Trino needs **explicit types** for struct fields and has **no** `* EXCEPT`; Iceberg forbids JSON and geography column types |
| Local engine | One DuckDB file, no services | **4 containers** (S3, Iceberg REST catalog, Trino, Spark), about 6 GB of images, plus 2 sha-pinned jars |
| Local build time | DuckDB: 19.96 s of model time on the **3.3M-row real data** (option 1 README) | Trino: ~65 s wall time for `dbt build` (198 nodes) on the **41,610-row fixture**; full round trip from an empty stack: 287 s. *Not comparable to the DuckDB figure (different data, different measure); option 2 has no real-data timing yet* |
| BigQuery compile in CI without a secret | Works out of the box (dbt v2) | Needs a **workaround** (throwaway key + `--no-populate-cache --no-introspect`) |
| CI (every PR) | Compile both targets + guardrail; DuckDB built and tested end to end (~30-51 s locally) | Model-tree check; compile both targets + guardrail; lakehouse up; **Spark** lands sources; Trino built and tested; macros executed; **Spark reads every table back** (~5 min) |
| Macro self-check executed | 47 cases on DuckDB | 59 cases on Trino (including microsecond and sub-cent checks) |
| Money vs BigQuery | `decimal(18,2)` vs `NUMERIC`: 21 of 29 models differ on money (measured, explained row by row) | `decimal(38,9)` = BigQuery `NUMERIC` exactly. Expected to close most of option 1's gap; **not yet measured** |
| A second consumer engine | None | **Spark**, through the shared Iceberg catalog: 12/12 tables read with identical profiles |
| Failure modes that only appear at read time | None | Spark cannot read Trino's Parquet v2 encodings unless a table property is set (5 of 12 tables failed without it); Spark cannot read dbt-trino views at all |
| Decisions that are not translations | Partitioning (BigQuery only) | Partitioning per engine (`day` on BigQuery, `month` on Iceberg: the daily layout **failed**); materialization decides who can read a model; table properties; three engines' time zones |
| Cross-adapter config friction | n/a | Trino configs warn as "custom keys" on BigQuery; a model-level `properties` replaces the project-level one |

## Building it: how much harder was option 2?

- **SQL portability was not the hard part.** Option 2's macro seam is the same size as
  option 1's, and the whole model tree ran on Trino with one model edit. 198 of 198 nodes
  passed after **one** fix, and that fix was physical layout, not SQL. The seam that
  option 1 built transferred almost entirely.
- **Most of option 2's effort went into the platform and the Spark boundary.** It needed
  a four-service lakehouse stack, image and download workarounds, a credential-free
  BigQuery compile, and two interop failures that only appeared when Spark read Trino's
  output: Parquet encodings, and views. None of those exist in option 1.
- **Option 2 needed a check option 1 does not have**: the Spark read-back gate
  (`scripts/spark_interop.py`). Without it, a dbt build that is green on Trino can still
  hand Spark unreadable tables. That is exactly what happened before the table property
  was added.

## Maintaining it: what each new model costs

| When someone adds or changes a model… | Option 1 | Option 2 |
|---|---|---|
| Must go through the macro seam | Yes (guardrail) | Yes (guardrail) |
| Must spell struct types, avoid star modifiers, and use only Iceberg-storable types | No | **Yes** (compiler error or build failure) |
| Must decide whether Spark reads it, and if so make it a table | No | **Yes** (interop gate) |
| A model-level `properties` must repeat the Spark-readability property | No | **Yes** (interop gate catches a miss) |
| Physical layout must be designed per engine | BigQuery only | BigQuery **and** Iceberg |
| CI time per PR | ~1 min | ~5 min |
| Infrastructure to keep current | DuckDB version, ADBC driver | Trino, Spark, Iceberg (jars must match the Spark version), REST catalog, object store, Docker images |
| dbt version upgrades | One (v2) | One (v1), independent of option 1's; the shared tree must keep working on both |

**Reading so far:** option 2 costs about the same to make portable, and noticeably more
to operate and keep correct. The extra cost is concentrated in one place, the
Trino ↔ Spark boundary, and every failure there is caught by an automated check in CI. In
return, option 2 gets exact `NUMERIC`-equivalent money (likely removing option 1's main
value gap, still to be measured) and a second engine (Spark) on the same data. Option 1
offers nothing comparable.

## What would change this assessment

1. **Building option 2's BigQuery leg and running value parity** (BigQuery vs Trino on the
   same real rows). If decimal(38,9) money does close the gap, option 2 has a correctness
   advantage over option 1. If Trino's decimal division differs, that is a new gap.
2. **Real data and a real cluster on option 2.** The ~65 s / 41,610-row fixture numbers
   say nothing about Trino or Spark performance at 3.3M rows or production scale, or about
   the cost of Spark's non-vectorized reader.
3. **Concurrency and table maintenance** (option 2 blind spots): both engines writing,
   snapshot expiry, compaction. These are operational costs option 1 does not have, and
   they are not measured.

Details: option 1 [`gaps.md`](../1_dbt_bigquery_duckdb/docs/gaps.md) /
[`challenges.md`](../1_dbt_bigquery_duckdb/docs/challenges.md); option 2
[`gaps.md`](../2_dbt_bigquery_trino_spark/docs/gaps.md) /
[`challenges.md`](../2_dbt_bigquery_trino_spark/docs/challenges.md) /
[`architecture.md`](../2_dbt_bigquery_trino_spark/docs/architecture.md).
