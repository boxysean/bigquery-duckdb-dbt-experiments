# bigquery-duckdb-dbt-experiments

**How much harder is it to build and maintain a polyglot dbt project on BigQuery + Trino
(with Spark) than on BigQuery + DuckDB?**

This repository answers that by building both, side by side. Both projects use **the same
models** and **the same source dataset**, so the difference between them is the platform.

| | Project | Targets | dbt | Second engine reached through |
|---|---|---|---|---|
| **1** | [`1_dbt_bigquery_duckdb/`](1_dbt_bigquery_duckdb/) | BigQuery, DuckDB | v2 (dbt-oss 2.0.5) | a local DuckDB file |
| **2** | [`2_dbt_bigquery_trino_spark/`](2_dbt_bigquery_trino_spark/) | BigQuery, Trino | v1 (dbt-core 1.11) | Trino over an Iceberg lakehouse that **Spark shares**: Spark lands the raw tables, dbt builds on Trino, Spark reads the marts |

The assessment so far is in **[`docs/comparison.md`](docs/comparison.md)**.

## What both projects share, and how that is enforced

- **The same source**: `bigquery-public-data.thelook_ecommerce` on the BigQuery target.
  Locally, both read the same deterministic fixture, defined once in
  `1_dbt_bigquery_duckdb/scripts/fixtures/thelook_ecommerce.sql`. Project 2 renders that
  file and has Spark land it as Iceberg tables.
- **The same end models**: 30 models and 168 data tests. Every `.sql` file under
  `models/` and `tests/` is **byte-identical** in both projects, every `.yml` file is
  structurally equal, and both expose the same 31 polyglot macro names.
  `scripts/check_model_trees.py` fails CI on any drift.
- **The same approach**: no engine-specific SQL in any model. Every dialect difference
  lives in `macros/polyglot/` (one implementation per engine), and each project's
  portability guardrail fails a PR that leaks a dialect token or branches on the target.

## Where each project stands

| Goal | Project 1: BigQuery + DuckDB | Project 2: BigQuery + Trino (+ Spark) |
|---|---|---|
| Polyglot macros | ✅ 29 macros, `bigquery__` / `default__` (DuckDB) | ✅ 29 macros, `bigquery__` / `trino__`; 59 self-check cases **executed** on Trino |
| Builds on the local engine | ✅ DuckDB | ✅ Trino: 198 / 198 (30 models, 168 tests) |
| Builds on BigQuery | ✅ built and value-measured on real data | ✅ built on real data: 197 pass, 1 warn (the deliberate dirty-data test), 0 error |
| Value parity measured | ✅ BigQuery vs DuckDB on the same real rows: row counts 29/29, money explained row by row | ✅ BigQuery vs Trino on the same real rows: **30/30 relations identical**, money exact to 9 decimals ([`value_parity.md`](2_dbt_bigquery_trino_spark/docs/value_parity.md)). Spark vs Trino: 12/12 tables identical |
| CI keeps it polyglot | ✅ [`1_dbt_bigquery_duckdb.yml`](.github/workflows/1_dbt_bigquery_duckdb.yml): both targets compile, guardrail, DuckDB built and tested | ✅ [`2_dbt_bigquery_trino_spark.yml`](.github/workflows/2_dbt_bigquery_trino_spark.yml): both targets compile, guardrail, full lakehouse round trip (Spark → dbt on Trino → Spark) |
| Gaps / challenges / blind spots documented | ✅ [`gaps`](1_dbt_bigquery_duckdb/docs/gaps.md), [`challenges`](1_dbt_bigquery_duckdb/docs/challenges.md) | ✅ [`gaps`](2_dbt_bigquery_trino_spark/docs/gaps.md), [`challenges`](2_dbt_bigquery_trino_spark/docs/challenges.md), [`architecture`](2_dbt_bigquery_trino_spark/docs/architecture.md) |

Plus, for both: [`repo.yml`](.github/workflows/repo.yml) runs the model-tree drift check.

## Layout

```
1_dbt_bigquery_duckdb/        project 1 (its own README, Makefile, pyproject, docs/)
2_dbt_bigquery_trino_spark/   project 2 (its own README, Makefile, pyproject, docs/, stack/)
docs/comparison.md            the comparison of the two
scripts/check_model_trees.py  the two projects still build the same models
archive/                      the earlier dbt v2 BigQuery + Spark experiment (not maintained)
.github/workflows/            one workflow per project, plus repo-level checks
```

Each project is self-contained: `cd` into it, `make setup`, then `make help`.

```bash
cd 1_dbt_bigquery_duckdb && make setup && make pre-pr     # DuckDB leg end to end
cd 2_dbt_bigquery_trino_spark && make setup && make pre-pr   # needs Docker; ~5 min from cold
python3 scripts/check_model_trees.py                       # from the repo root (needs PyYAML)
```

## Why Trino and Spark are wired this way

Trino has no connector that sends a query to Spark. In practice, Trino and Spark
cooperate by sharing **tables**: one Iceberg catalog, one object store. Spark-produced
data reaches Trino (and dbt) as tables Trino reads directly, and dbt's output reaches
Spark the same way. Project 2 is built and checked around that, including the rules a
model must follow for Spark to be able to read it. See
[`2_dbt_bigquery_trino_spark/docs/architecture.md`](2_dbt_bigquery_trino_spark/docs/architecture.md).
