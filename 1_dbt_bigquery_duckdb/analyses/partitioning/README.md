# Partitioning and clustering: one fact table, measured on BigQuery

BigQuery bills a query by the bytes it scans, and a table's physical layout decides how
many bytes a filtered query has to scan. DuckDB has neither: a local columnar file has
no per-byte bill, and dbt-duckdb has no `partition_by` or `cluster_by` config. This
directory is the measurement of what the layout buys on BigQuery for the largest fact
table, with the DuckDB leg left exactly as it was.

* model: `models/marts/fct_inventory_items.sql`
* seam: `macros/polyglot/physical.sql` (`physical_layout()`)
* results: [`results.md`](results.md) (window `2024-06`, measured 2026-10-07), from
  `results.before.json` and `results.after.json` beside it and `logs/{before,after}.log`;
  this file states the method

## Why this table

Measured from BigQuery table metadata on 2026-10-07, in `coreychimpbot.experiments_dev`:

| table | rows | bytes |
|---|---|---|
| `fct_inventory_items` | 488,895 | 49,525,078 |
| `fct_order_items` | 181,070 | 45,581,586 |

`fct_inventory_items` is the largest fact table by both measures, so it is the one
where a pruned scan has the most to save.

## Why the two engines diverge here

The layout is a storage decision, not a change to the rows: the model's columns,
filters and joins are untouched, and both engines deliver the same relation. What
differs is which config keys exist. On BigQuery, partitioning by day splits the table
into one storage unit per UTC day of `created_at`, so a filter on `created_at` skips
whole days without reading them; clustering sorts the blocks inside each partition by
`product_id`, so a filter on `product_id` reads fewer blocks. Neither key means
anything to DuckDB.

So the model never names the keys. Its config call splats the dict that the
`physical_layout()` macro returns. That macro dispatches like every other entry in
`macros/polyglot/`: the BigQuery implementation returns the partition and cluster keys
below, the default implementation returns an empty dict, and DuckDB builds a plain
table. No file under `models/` branches on the target, and the literal key names never
appear there, so `scripts/check_portability.py` and the `partition_by` / `cluster_by`
rules of `scripts/move_to_duckdb.py` see nothing to flag.

## Keys

| key | value |
|---|---|
| partition field | `created_at` |
| partition data type | `timestamp` |
| partition granularity | `day` |
| cluster columns | `product_id` |

`created_at` carries a `not_null` test on this model, so no row should land in the
`__NULL__` partition.

## What will be measured

The harness is `scripts/bq_partition_measure.py` (`make partition-measure ARGS=...`).
It measures one table, `fct_inventory_items`, twice:

1. **before**: the table as built without the layout (the tree as it was before this
   card, i.e. a plain table);
2. **after**: the table as built through `physical_layout()`.

The window is one calendar month, given as `--window YYYY-MM`. The representative
query reads that whole month on `created_at` and selects every column: the point is
what partition pruning does to a scan that would otherwise read the whole table, so the
query filters on the partition column only and does not aggregate. Each leg (`measure`)
records:

* **table metadata** from `tables.get` (a metadata read, bills nothing): `numRows`,
  `numBytes`, `timePartitioning`, `clustering.fields` (each printed as `none` when
  absent), `creationTime`, `lastModifiedTime`;
* **three executed queries and one dry run**, each submitted with `jobs.insert` and,
  except the dry run, read back with `jobs.get`:
  * `dry_run`: the filtered query with `dryRun: true`, BigQuery's free estimate, kept
    as a cross-check against the executed job (on a clustered table the estimate can
    be an upper bound, since cluster pruning is only known at execution time);
  * `full_scan`: `SELECT *` of the table, the whole-table cost;
  * `filtered_scan`: `SELECT *` with `created_at >= TIMESTAMP '<YYYY-MM-01 00:00:00>'
    AND created_at < TIMESTAMP '<first instant of the next month>'`, the representative
    query;
  * `filtered_count`: `COUNT(*)` with the same filter, the control that shows the
    10 MB per-query minimum flooring the billed figure;
* **rows per partition** from the dataset's `INFORMATION_SCHEMA.PARTITIONS`: partition
  count, first and last `partition_id`, the `__UNPARTITIONED__` row when present, the
  window's rows, and the rows over real partitions. On the plain table this is a
  single unpartitioned row, which is a valid answer.

For each executed job the harness reads `totalBytesProcessed`, `totalBytesBilled`,
`cacheHit`, `statementType`, the schema's field count, `creationTime`, `endTime`,
`totalSlotMs` and the `jobId`, so every number can be looked up again. Every executed
job carries `useQueryCache: false`, and `cacheHit` must be `false`: a cached job bills
0 and measures nothing, so a cache hit makes the run unusable (exit 1). Every executed
job also carries `maximumBytesBilled` from `BQ_MAXIMUM_BYTES_BILLED` (default
1000000000, the profile's 1 GB); a job refused by it is recorded as refused with
BigQuery's own message, not retried with a higher ceiling.

`report` compares a `before` and an `after` run **of the same table and window**, and
refuses (exit 1) when the two files are not that pair, when either is missing, or when
either recorded a cache hit. It writes `results.md`: the metadata side by side, one
table per query (bytes processed and billed, before, after, absolute and percentage
delta, a one-line reading), and the partition summary.

Every query bills at least the 10 MB per-query minimum, so for a table this size the
billed figure may move less than the processed figure; both are reported, and the
reading is stated in those terms.

## How to run it

With `BQ_KEYFILE` exported, from the repository root. The before leg is a scratch copy
of this tree with the model's `physical_layout()` config line removed, built into the
same dataset as the after leg, so both legs measure the same table name:

    mkdir -p target/partition_before
    tar cf - --exclude=./.git --exclude=./.venv --exclude=./target --exclude=./dev.duckdb . \
        | (cd target/partition_before && tar xf -)
    # delete the `physical_layout()` config line from
    # target/partition_before/models/marts/fct_inventory_items.sql, then:
    (cd target/partition_before && DBT_ENV=partition DBT_PROFILES_DIR="$PWD" BQ_KEYFILE=<key> \
        ../../.venv/bin/dbt run --target bigquery --select +fct_inventory_items)
    make partition-measure ARGS="measure --table coreychimpbot.experiments_partition.fct_inventory_items --label before --window 2024-06"
    DBT_ENV=partition make bq
    make partition-measure ARGS="measure --table coreychimpbot.experiments_partition.fct_inventory_items --label after --window 2024-06"
    make partition-measure ARGS="report --before analyses/partitioning/results.before.json --after analyses/partitioning/results.after.json"

`measure` writes `logs/<label>.log` and `results.<label>.json` here; `report` writes
`results.md`.

## Constraints

* The 1 GB `maximum_bytes_billed` ceiling on the BigQuery profile (`profiles.yml`,
  `BQ_MAXIMUM_BYTES_BILLED`) stays in place for every query in this measurement. It is
  not raised to make a query fit.
* No billable query goes into a dbt test. The measurement is a harness run by hand,
  outside `dbt build`.
* The DuckDB leg is not measured here and does not change: `dbt build --target duckdb`
  builds the same plain table it built before this card.

## What this does not establish

* One table, one query shape. It does not say which layout is best for other marts,
  nor for queries that do not filter on `created_at` or `product_id`.
* Slot time and wall time are recorded only as context; on a table of ~50 MB they are
  dominated by job overhead, and the claim is about bytes.
