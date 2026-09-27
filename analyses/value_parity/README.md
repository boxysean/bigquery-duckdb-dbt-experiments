# Value parity: one real dataset, both targets, every model compared

Until this card the DuckDB leg read the generated fixture and the BigQuery leg the real
`bigquery-public-data.thelook_ecommerce`, so `make parity` could establish schema parity
only. Here both legs read **the same input rows** and every model's delivered relation is
compared value by value.

* loader: `scripts/load_duckdb_real_sources.sh` (`make fixtures-real`)
* harness: `scripts/parity.py --sources real --bq-source materialised --same-data`
  (`make value-parity` runs the loader, both builds and the comparison)
* generated result: `results.md` (per model: equality, rows, differences, both build
  durations), `results.json` (the full report)
* probes: `probes/*.py`, run through `probes/run.sh <name>`
* raw output: `logs/` (the bytes the commands printed; the key path is redacted)

| log | what printed it |
|---|---|
| `loader.log` | `scripts/load_duckdb_real_sources.sh` (D2-mapped load into `dev.duckdb`) |
| `loader-raw-timestamps.log` | `scripts/load_duckdb_real_sources.sh --raw-timestamps` (the D2 probe, into `target/raw_timestamps.duckdb`) |
| `dbt_build_duckdb.log`, `run_results_duckdb.json` | `dbt build --target duckdb` over the real rows |
| `dbt_build_bigquery.log`, `run_results_bigquery.json` | `dbt build --target bigquery` into `coreychimpbot.experiments_dev` |
| `dbt_build_duckdb_baseline.log` | the DuckDB rebuild of the baseline step (only when parity.py builds) |
| `parity.log` | `scripts/parity.py` itself |
| `probe_decimal_text.log` | `probes/decimal_text.py` |
| `probe_scale_attribution.log` | `probes/scale_attribution.py` |

## Reproduce

```
export BQ_KEYFILE=/path/to/service-account.json
make value-parity                 # loader, both builds, comparison; exit 1 = values differ
bash analyses/value_parity/probes/run.sh decimal_text
bash analyses/value_parity/probes/run.sh scale_attribution   # after a --sources real run
bash scripts/load_duckdb_real_sources.sh --raw-timestamps     # the D2 probe, scratch file
```

`make fixtures` (and `make duck`, `make polyglot`, `make pre-pr`) puts the fixture back
into `dev.duckdb`; `parity.py --sources real` refuses to start on the fixture or on a
raw-timestamp load.

## Why Transport A (the extension), not Transport B (files)

* The DuckDB leg reads the real rows through the project's own source declaration
  (`models/staging/_thelook__sources.yml`), with no change to `models/`, `macros/` or
  `tests/`.
* Transport B (`EXPORT DATA` to GCS as Parquet) puts a second representation between
  BigQuery and the DuckDB leg, so a value difference could be an export-format artifact
  rather than a model or dialect difference. It also needs a writable bucket.
* Measured by the orchestrator before this run: all seven tables, 510,949,141 bytes,
  materialised into one scratch DuckDB in 37.0 s wall; `orders` (124,952 rows) alone in
  2.29 s. This run's own per-table times are in `logs/loader.log`.

## The timestamp mapping (D2)

The source contract says a timestamp is an absolute instant (`TIMESTAMPTZ` on DuckDB),
and the DuckDB branch of `to_utc_timestamp` (`macros/polyglot/casting.sql:49-51`)
relies on it. The extension returns a BigQuery `TIMESTAMP` as a zone-less DuckDB
`TIMESTAMP`, so the loader delivers every timestamp column as
`to_timestamp(epoch_us(c) / 1000000.0)` and proves, row by row against the raw copy
(`POSITIONAL JOIN`), that no instant moved. `--raw-timestamps` skips the mapping and its
log reports what the macro would do to the raw values: see `logs/loader-raw-timestamps.log`.

## What the harness compares

Per model, on the relation each leg delivered (DuckDB `dev.duckdb` `main.<model>`,
BigQuery `coreychimpbot.experiments_dev.<model>`): row count, column names, canonical
column types, and per column an order-independent checksum, a null count and a
distinct count. See `scripts/parity.py` (TRAPS) for the canonical renderings. The digest
self-check runs on constants on both engines before any model is measured; it now
includes decimals with trailing zeros, because DuckDB prints `DECIMAL(18,2)` at its
declared scale (`12.30`) and BigQuery prints `NUMERIC` in the shortest form (`12.3`)
(`logs/probe_decimal_text.log`).

## What this does not establish

* One dataset, one run of each build, on one box; the durations are single runs.
* The comparison is an aggregate per column (checksum, nulls, distinct). It says *that* a
  column differs, not which rows; `probes/scale_attribution.py` narrows the cause per
  column but does not join the two legs row by row.
* Models only. dbt's tests were run by both builds (see the build logs) but are not
  compared by the harness.
