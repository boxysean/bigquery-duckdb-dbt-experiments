# bigquery_spark: one dbt project, two engines (BigQuery and Spark)

The same dbt model tree (29 models over the public `thelook_ecommerce` dataset), built and
tested against **BigQuery** and **Spark 4.2.0**, with a guardrail that keeps it portable and a
harness that compares what the two engines produce on the same rows. Its purpose is to answer,
with measurements, what moving a BigQuery dbt project to Spark costs.

**Start with the deliverables:**

* [`docs/bigquery-to-spark.md`](docs/bigquery-to-spark.md): the incompatibility catalogue, one
  row per construct, each cell measured on both engines or citing the macro that handles it.
* [`docs/conclusion.md`](docs/conclusion.md): the plain-language conclusion for a
  decision-maker.
* [`SPEC.md`](SPEC.md): the design contract. [`NOTES.md`](NOTES.md): the build history and every
  raw measurement (§9 the gates, §10 the construct probes).
* [`parity-report.md`](parity-report.md): the latest value-parity run (Spark vs BigQuery on the
  same rows).

## What is verified (2026-10-07)

| | result |
|---|---|
| `dbt build --target spark` | exit 0: 29 models, 167 tests, 196 total: 195 success, 1 warn |
| `dbt build --target bigquery` | exit 0: the same numbers |
| `scripts/check_portability.py` | exit 0: 30 compiled files, 0/13 and 0/12 foreign tokens, 0 target branches, `PORTABLE` |
| `scripts/parity.py --same-data` | 29 of 29 models executed on both engines, 0 not measured; sources 7 of 7 identical; **8 of 29 match on every check, 21 differ on money values only, 0 differ on names or types**; the money prediction is CONFIRMED (54 decimal columns differ row by row) |

The one warn is `tests/assert_order_item_created_at_is_plausible`, `severity: warn` by design.
Nothing is compile-only: every model ran on both engines. Section 5 of the catalogue has the
details and the list of what is **unverified**.

## The shape

* **Two targets, one folder.** `spark` (the default target) and `bigquery`, both in this
  folder's own `profiles.yml`, under this folder's own `dbt_project.yml` (project and profile
  `bq_spark_experiments`). The root project of this repository is a separate, unrelated
  two-engine project; nothing here reads or edits its files, and its guardrail never scans this
  tree.
* **Why a sibling folder and not an example:** this is a second, independent peer project, not
  a worked example. The folder name says its two engines, and its own `dbt_project.yml` and
  `profiles.yml` keep the root project's files and portability scan untouched.
* **One model tree, no target branches.** Models never test which engine they run on. Every
  dialect difference lives in `macros/polyglot/`: each macro has a `default__` branch (Spark)
  and a `bigquery__` branch, dispatched through the `bq_spark_experiments` namespace.
* **The same rows on both sides.** BigQuery reads `bigquery-public-data.thelook_ecommerce`
  live. Spark reads a Parquet snapshot of the same seven tables, pulled with BigQuery table
  reads (0 bytes billed) by `scripts/load_spark_sources.py` and registered as
  `thelook_ecommerce.<table>`.

## What you need

| need | for | how |
|---|---|---|
| dbt-oss 2.0.5 | everything | `uv sync` in the repository root (the Makefile uses `../.venv/bin/dbt`) |
| JDK 21 + `pyspark==4.2.0` + the BigQuery Python client | Spark, the loader | `make setup` (installs under `~/.local/spark`, no sudo) |
| **the Spark endpoint** on `127.0.0.1:10000` | `make spark`, `make portability` (compiling the Spark target), `make parity`, `make pre-pr` | `make start-spark`. dbt-oss has no in-process Spark mode: a running Thrift Server is required |
| `DBT_ALLOW_EXPERIMENTAL_ADAPTERS=true` | every dbt call | exported by the Makefile and the scripts; dbt-oss 2.0.5 refuses the Spark adapter without it |
| **a BigQuery credential** | `make bq`, `make load-sources`, `make parity`, `make value-parity`, `make pre-pr` | `BQ_KEYFILE` (defaults to `~/.config/gcp/coreychimpbot-sa.json` when that file exists) or gcloud application-default credentials. Without one, these refuse with exit 2 |
| **the loaded sources** in Spark | `make spark`, the parity steps | `make load-sources` (the `events` table, ~2.4M rows, takes minutes). Reload before comparing: the public dataset changes over time |

Costs: BigQuery queries are capped at 1 GB billed each (`BQ_MAXIMUM_BYTES_BILLED`). The full
value-parity run took 60 minutes and billed 2.8 GB on 2026-10-07.

## Quick start

```bash
cd bigquery_spark
make check-env      # every prerequisite for both targets; the credential is reported, not required
make start-spark    # the Spark 4.2.0 Thrift Server on 127.0.0.1:10000 (UTC session)
make spark          # start-spark + check-env + load-sources, then dbt build --target spark
make bq             # dbt build --target bigquery (needs the credential)
make portability    # compile both targets, scan each render for the other dialect and for target branches
make parity         # scripts/parity.py with its default, --same-data: values gate too (~60 min, ~2.8 GB)
make value-parity   # load-sources first, then parity --same-data, logged to target/value_parity.log
make pre-pr         # check-env + portability + STRUCTURAL parity (--no-same-data), see below
```

Other targets: `make stop-spark`, `make load-sources` (`TABLES=a,b` for a subset), `make
polyglot` (the macro layer's self-check on both engines, plus the Spark decimal ceiling
failing by design), `make clean` (also deletes the Parquet the Spark tables point at; run
`make load-sources` again afterwards). `make help` lists them all.

### `make pre-pr` and why it does not compare values

`scripts/pre_pr.sh` runs `check_env.sh`, `check_portability.py` and `parity.py
--no-same-data`, prints `ok` / `FAIL` / `n/a` per step, and exits 0 (all ok), 1 (a real
finding) or 2 (a leg could not be measured: no endpoint, no credential, no sources). `make`
itself reports either non-zero exit as `Error`; run `bash scripts/pre_pr.sh` directly when
1 vs 2 matters.

The parity step is structural on purpose: it runs every model on both engines but gates only on
column names, canonical types and the harness's own self-check. Comparing values is the
separate, deliberate `make value-parity` step, because its result is known and catalogued: 21
of 29 models differ on money (Spark `decimal(18,2)` keeps cents, BigQuery `NUMERIC` keeps nine
decimals). A gate that ran it would fail on every change regardless of the code. `pre_pr.sh`
keeps the value report in `parity-report.md` intact and writes its own report to
`target/pre_pr/`.

## Layout

```
bigquery_spark/
  README.md                this file
  SPEC.md                  the design contract
  NOTES.md                 build history and every raw measurement
  dbt_project.yml          project bq_spark_experiments
  profiles.yml             two outputs: spark (local Thrift, default) and bigquery; no secrets
  packages.yml             empty
  Makefile                 the targets above
  models/
    staging/               7 models over the sources (+ _thelook__sources.yml, the one file allowed to read the target)
    intermediate/          11 models
    marts/                 11 models (dim_date carries the one rewrite: unnest -> explode_array_rows)
  macros/polyglot/         the two-engine seam: types, casting, dates, arrays, keys, math,
                           selection, strings, structs, and self_check.sql (polyglot_render,
                           polyglot_selfcheck)
  tests/                   4 singular tests (plus 163 generic tests declared in the ymls)
  analyses/
    polyglot_showcase.sql  the macro showcase (compiled and scanned by the guardrail)
  scripts/
    install_prereqs.sh     JDK 21 + pyspark 4.2.0 + BigQuery client under ~/.local/spark
    start_spark.sh         start the Thrift Server (reports an already-running one)
    stop_spark.sh          stop it, only if the listener really is a Spark Thrift Server
    check_env.sh           prerequisites for both targets
    load_spark_sources.py  real BigQuery rows -> Parquet -> Spark tables, row counts gated
    check_portability.py   the two-target guardrail (--demo proves it can fail)
    parity.py              Spark vs BigQuery per model and per column; writes parity-report.*
    pre_pr.sh              the pre-PR routine
  docs/
    bigquery-to-spark.md   the incompatibility catalogue
    conclusion.md          the decision-maker conclusion
  parity-report.md/.json   the latest value-parity result
```
