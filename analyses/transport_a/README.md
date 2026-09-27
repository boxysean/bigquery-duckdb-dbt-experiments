# Transport A: DuckDB reading BigQuery directly, measured

DuckDB (the CLI and the `duckdb` dbt adapter) can read BigQuery through the
**community** `bigquery` extension, using the BigQuery **Storage Read API** for table
reads and the **REST API** for query jobs. This directory is the measurement of that
path: every number below has a scenario file, a log with the raw output, and a command
that reproduces it.

* harness: `scripts/transport_a_measure.py`
* scenarios: `analyses/transport_a/sql/*.sql` (one DuckDB process each)
* raw output: `analyses/transport_a/logs/*.log` (stdout + stderr + the exact SQL as run)
* generated table: `analyses/transport_a/results.md`, machine-readable `results.json`

Run of record: **2026-09-27 15:19 UTC**, DuckDB **v1.5.5 (Variegata) d8cdaa33fd**,
extension build **27d85ad** (`installed_from = community`), 3 CPUs, data in
`bigquery-public-data`, billing/quota project `coreychimpbot`, service account
`coreychimpbot@coreychimpbot.iam.gserviceaccount.com`. The suite was run three times
end to end; where a number moves between runs, all of them are shown.

## Reproduce

```
export BQ_KEYFILE=/path/to/service-account.json   # the box's path is in the team runbook
python3 scripts/transport_a_measure.py            # the whole suite, ~4 minutes
python3 scripts/transport_a_measure.py --only t05 t13   # one or two scenarios
python3 scripts/transport_a_measure.py --list
```

or, the same thing, `make transport-a`.

The key path is substituted into the `.sql` files at run time (placeholder
`__SA_PATH__`); no scenario file contains it. Wall time is measured around the DuckDB
process; peak RSS is `/usr/bin/time -v` for that process. `__RUN_ID__` is a per-run
timestamp that makes the dry-run/billing scenarios' GoogleSQL text unique, so
BigQuery's result cache cannot answer them.

## Results

`analyses/transport_a/results.md` is generated; the numbers are summarised here.

| # | what | wall s | peak RSS MiB | outcome |
|---|---|---|---|---|
| t01 | `INSTALL bigquery` from the core repo | 0.26 | 27 | **fails**: HTTP 404 on `extensions.duckdb.org/.../bigquery.duckdb_extension.gz` |
| t02 | `INSTALL bigquery FROM community` | 3.31 | 211 | ok, build `27d85ad`, `installed_from = community` |
| t03 | secret `SCOPE` vs the data project | 3.58 | 59 | **fails** against `bigquery-public-data` (ADC fallback); the same file's billing-scoped query works |
| t04 | `SCOPE 'bq://bigquery-public-data'` + `billing_project` | 3.91 | 62 | ok, `usa_names.usa_1910_2013` = **5,552,452 rows** |
| t05 | `WHERE` pushdown | 1.77 | 57 | pushed: `` `state` = "CA" AND `year` >= 2000 ``, 95,373 rows |
| t06 | column pruning | 10.41 | 68 | pushed; see the per-query times below |
| t07 | dry run vs billed bytes | 10.74 | 90 | predicted 111,049,040; the real job processed **111,049,040** |
| t07b | one shape, cache defeated | 9.24 | 89 | predicted 44,419,616; the real job processed **44,419,616** |
| t08 | aggregate pushdown **off** (default) | 1.78 | 61 | filter pushed, `GROUP BY`/`SUM` local |
| t09 | aggregate pushdown **on** (experimental) | 2.12 | 53 | whole aggregate becomes a remote GoogleSQL query job |
| t10 | `ATTACH` one dataset, `READ_ONLY` | 11.54 | 67 | works: dataset lists 2 tables, counts 5,552,452 |
| t11 | `ATTACH` a whole project | 32.70 | 195 | **fails both ways** (see failure modes) |
| t12 | `READ_ONLY` guard + writable DDL | 5.57 | 54 | guard refused locally; writable catalog created the probe table |
| t12b | writable: insert, read back, drop | 16.43 | 59 | row written and verified by a query job (n=1); 11.3 s of it is the insert |
| t12c | leftover check from BigQuery | 6.97 | 58 | 0 probe tables, 29 tables in `experiments_dev` |
| t13 | read parallelism | 20.19 | 69 | no reproducible gain from more streams (see below) |
| t14 | materialize the whole table locally | 12.20 | 130 | **5,552,452 rows**, 51 states, 1910–2013, `sum(number)` 295,727,065 |
| t15 | type fidelity, Storage path | 8.26 | 61 | see the type table |
| t16 | type fidelity, REST path | 4.66 | 51 | same types; `BIGNUMERIC` unpadded text |
| t17 | REST decoder failure mode | 4.06 | 60 | **fails**: `Failed to cast value: Unimplemented type for cast (GEOMETRY('OGC:CRS84') -> BIGINT[])` |
| t18 | dry-run result projection | 0.84 | 50 | **crashes**: `INTERNAL Error: Attempted to access index 2 within vector of size 2` |

Wall times are single runs on a shared box and vary run to run: t14 was 11.9 s, 11.2 s
and 22.2 s across the three runs, t12b 16.4 s, 93.2 s and 133.5 s, t13 20.2 s, 18.1 s
and 24.3 s. The bytes and row counts are stable; treat the seconds as ±50%.

### Pushdown: filters and projections reach BigQuery (t05, t06, t08)

`SET bq_debug_show_queries = true` prints what the extension hands to BigQuery:

```
BigQuery selected fields: state, year
BigQuery row restrictions: `state` = "CA" AND `year` >= 2000
```

* t06(a) `count(*)` → `selected fields: state` (one column, not zero — 3.90 s)
* t06(b) `sum(number) WHERE year = 2000` → `year, number` + `` `year` = 2000 `` (1.36 s)
* t06(c) `count(DISTINCT state), sum(number) WHERE year = 2000` → `year, state, number` (1.81 s)
* t06(d) `WHERE gender IS NOT NULL` → `gender` (3.11 s)

So column pruning is real, and it is what drives cost: the logs of t07 show the same
aggregate costing 111,049,040 bytes when it needs `state, number, year` and 66,629,424
bytes when `year` is not referenced. One oddity worth knowing: `count(*)` still comes
back with `selected fields: state` and costs 3.9 s, i.e. the reader asks for a column the
query does not need (that attribution is an inference from the debug line plus the
timing, not something the extension reports). `count(*)` answered from table metadata —
0 bytes — only happens on the `bigquery_query` path, not on a scan.

### Aggregate pushdown is off by default and does what it says (t08, t09)

**off** (default): `BigQuery row restrictions: `year` = 2000`, no remote job — the sum
is computed locally over the transferred rows.

**on** (`SET bq_enable_aggregate_pushdown = true`, experimental): the whole aggregate
becomes one query job:

```
query: SELECT `state` AS __duckdb_bq_group_0, SUM(`number`) AS __duckdb_bq_aggr_0
       FROM `bigquery-public-data.usa_names.usa_1910_2013` WHERE `year` = 2000 GROUP BY `state`
query: SELECT SUM(`number`) AS __duckdb_bq_aggr_0
       FROM `bigquery-public-data.usa_names.usa_1910_2013`
```

Scenario wall time 1.78 s (off) vs 2.12 s (on) for a 5.5 M-row table: on this data size
the saving is not visible; what changes is *where* the work happens. The setting is
documented as experimental with different GoogleSQL cast/string/float semantics and no
local retry after a remote job starts, so it is a deliberate opt-in.

### Cost guard: dry run predicts the real bytes exactly (t07, t07b)

```
-- t07b, the comparable pair (the /* t07b __RUN_ID__ */ comment defeats the result cache)
SELECT * FROM bigquery_query('bigquery-public-data',
  'SELECT /* t07b <run-id> */ COUNT(*) AS n FROM `bigquery-public-data.usa_names.usa_1910_2013` WHERE year = 2000',
  dry_run := true, billing_project := 'coreychimpbot');      -- total_bytes_processed 44,419,616, cache_hit false
SELECT * FROM bigquery_query('bigquery-public-data',
  'SELECT /* t07b <run-id> */ COUNT(*) AS n FROM `bigquery-public-data.usa_names.usa_1910_2013` WHERE year = 2000',
  billing_project := 'coreychimpbot');                        -- 79,966 (one row)
```

then `bigquery_jobs('coreychimpbot')` shows the job that ran it:

| shape | dry run bytes | job bytes processed | slot time |
|---|---|---|---|
| `COUNT(*) WHERE year = 2000` | 44,419,616 | **44,419,616** | — |
| `state, SUM(number) WHERE year = 2000 GROUP BY state` | 111,049,040 | **111,049,040** | 161 ms |
| `state, SUM(number) GROUP BY state` (no filter, no `year`) | 66,629,424 | — | — |

Two caveats measured, not assumed:

* **Billing floor**: a query that processes less than 10 MiB is billed 10 MiB; the
  44.4 MB row above is billed in full (≈42.4 MiB).
* **Result cache**: repeating identical SQL is answered from BigQuery's result cache —
  those jobs report `bytes_processed = 0` (visible in t07's job list). A dry run of a
  cached shape reports `cache_hit = true` and still prints the would-process bytes.
* `dry_run` works **only** as `SELECT *` — projecting a column out of the dry-run result
  crashes the extension (t18).

### Read parallelism: no measurable win on this box (t13)

Same query (all 5 columns of the 5.5 M-row table transferred), 3 CPUs, seconds per run
(run of record first):

| variant | wall s |
|---|---|
| `preserve_insertion_order = true`, `bq_max_read_streams = 0` (defaults) | 4.25 / 3.71 / 4.60 |
| `preserve_insertion_order = false`, `bq_max_read_streams = 0` (one stream per thread) | 3.94 / 3.32 / 4.42 |
| `preserve_insertion_order = false`, `bq_max_read_streams = 1` (forced single stream) | 3.77 / 3.46 / 4.46 |
| `preserve_insertion_order = false`, `bq_max_read_streams = 8` | 3.96 / 3.69 / 4.51 |
| `threads = 1`, `bq_max_read_streams = 0` | 4.01 / 3.64 / 5.84 |

Every variant is within the run-to-run spread. Forcing a **single** stream costs nothing
versus three or eight, and one thread is in the same band: the read is not stream-bound.
CPU time inside the process (user+sys ≈ 3–3.5 s of the ~4 s) says the cost is local Arrow
decoding, not the wire. On this hardware the parallelism knobs are not worth touching; on
a larger table or a slower client they may be — this box cannot answer that, because the
default already matches its 3 CPUs.

### Type fidelity across the wire (t15 Storage, t16 REST)

`typeof()` on every column of one `bigquery_query` result, plus values:

| BigQuery | DuckDB (Storage path) | returned value |
|---|---|---|
| `BIGNUMERIC` (39 significant digits) | `VARCHAR` | `123456789012345678901234567890.123456789000...` (padded to 76 digits) |
| `NUMERIC` | `DECIMAL(38,9)` | `1.230000000` |
| `GEOGRAPHY` | `GEOMETRY('OGC:CRS84')` | `POINT (-122.4 37.7)` |
| `ARRAY<INT64>` | `BIGINT[]` | `[1, 2, 3]` |
| `ARRAY<STRING>` | `VARCHAR[]` | `[a, b]` |
| `STRUCT<a INT64, b STRING>` | `STRUCT(a BIGINT, b VARCHAR)` | `{'a': 1, 'b': x}` |
| `TIMESTAMP` | `TIMESTAMP` (not `TIMESTAMPTZ`) | `2024-01-02 03:04:05` (UTC, no zone) |
| `DATETIME` | `TIMESTAMP` | `2024-01-02 03:04:05.678901` |
| `TIME` | `TIME` | `03:04:05.678901` |
| `JSON` | `VARCHAR` | `{"k":1}` |
| `BYTES` | `BLOB` | `\x01\x02` |
| `INTERVAL` | `INTERVAL` | `1 day` |

Notes that matter for a warehouse:

* **`TIMESTAMP` stays zone-less.** A BigQuery `TIMESTAMP` (an absolute instant, UTC)
  arrives as DuckDB `TIMESTAMP`, not `TIMESTAMPTZ`. Verified on real data:
  `thelook_ecommerce.orders.created_at` is `TIMESTAMP`, 124,952 rows, range
  2019-01-15 07:03:47 → 2026-09-27 00:38:27.945885. Any comparison against DuckDB
  `TIMESTAMPTZ` or a local-time assumption has to be explicit.
* **`BIGNUMERIC` never becomes a number.** Default `bq_bignumeric_as_varchar = true`;
  setting it `false` still returned `VARCHAR` for `CAST('1.23' AS BIGNUMERIC)` on the
  REST path. DuckDB `DECIMAL` caps at 38 digits and BigQuery's `BIGNUMERIC` has 76, so
  the ceiling is inherent, not a setting.
* **The two paths differ in text, not types.** The REST path returns the exact
  `BIGNUMERIC` text (`...123456789`), the Storage path pads it to the full 76 digits —
  same value, same `VARCHAR` type, different string.
* **`GEOGRAPHY` → `GEOMETRY('OGC:CRS84')`** with WKT at the boundary, on both paths; a
  real `GEOGRAPHY` column (`geo_us_boundaries.counties`, 3,233 rows) comes back as
  `geometry('ogc:crs84')` for `int_point_geom` and `county_geom`.

### Read path works end to end; the read-session 404 does not reproduce (t14)

The card carried a signal that Storage Read API read-session creation returns HTTP 404 on
this project. Through the extension it does not: t14 materializes the entire
5,552,452-row table into a local DuckDB file in 11.9 s (11.2 s and 22.2 s in the other
two runs) and the local copy checks out — 51 states, years 1910–2013, `sum(number)` =
295,727,065. Every scan in this suite goes through the same read path (the extension's
docs say Storage Read API, and it exposes `grpc_endpoint` for it); nothing 404s. The only
404s seen in the suite are the *core-repo extension download* (t01) and a Storage
**Write** `NOT_FOUND` (t12b).

## Attach modes

```
-- one dataset, read-only, public data paid by another project  (t10 — works)
ATTACH 'project=bigquery-public-data dataset=usa_names billing_project=coreychimpbot'
   AS bqnames (TYPE bigquery, READ_ONLY);
SELECT count(*) FROM bqnames.main.usa_1910_2013;   -- 5,552,452

-- whole project  (t11 — fails, both with and without billing_project)
ATTACH 'project=bigquery-public-data' AS bq_data (TYPE bigquery, READ_ONLY);
```

`READ_ONLY` is a **local guard**: `CREATE TABLE` through it fails before any remote call
(``Invalid Input Error: Cannot execute statement of type "CREATE" on database "bq_ro"
which is attached in read-only mode!``). Dropping `READ_ONLY` reaches BigQuery: the
probe table was created, a row inserted through the catalog, the row confirmed by a
query job (`n = 1`), then dropped — and `INFORMATION_SCHEMA.TABLES` (queried remotely)
shows **0** probe tables and the 29 dbt tables still in place.

Writing is the weakest leg of this transport, and it is the one number that swings
hardest: the insert took 11.3 s in the run of record and 128.7 s in another run, with 82
`Retrying...` lines from the Storage Write API in the slow one. Inserting into a table
created moments earlier **in the same session** failed outright
(`Failed to create write stream: NOT_FOUND ... Cannot create BigQuery write stream to
projects/coreychimpbot/datasets/experiments_dev/tables/transport_a_probe`) while the
same insert worked in a fresh session. Not a permission problem — the DDL and the write
both landed. Read the timings, not the SQL, as the finding.

## Failure modes, with the error text

**1. The extension is community-only (t01).**

```
HTTP Error: Failed to download extension "bigquery" at URL
  "http://extensions.duckdb.org/v1.5.5/linux_amd64/bigquery.duckdb_extension.gz" (HTTP 404)
Candidate extensions: "icu", "iceberg", "parquet", "inet", "quack"
```

Reproduced against the pinned v1.5.5 with an empty `HOME`, so it is not a cache miss.
`INSTALL bigquery FROM community` in the same conditions succeeds (build `27d85ad`).

**2. The secret `SCOPE` follows the data, not the money (t03).** With
`CREATE SECRET (TYPE bigquery, SCOPE 'bq://coreychimpbot', ...)` a read of
`bigquery-public-data` falls back to Application Default Credentials:

```
Invalid Input Error: BigQuery Authentication Failed
No usable authentication credentials were found. ...
Underlying authentication error:
  PerformWork() - CURL error [6]=Could not resolve hostname
```

`CURL error [6]` is the metadata-server lookup failing on a non-GCE box; the message
looks like a broken environment, which is exactly why it wastes an afternoon. The fix is
one line: `SCOPE 'bq://bigquery-public-data'` plus `billing_project := 'coreychimpbot'`.
Per-project secrets can coexist, and `SECRET <name>` on `ATTACH` selects one explicitly.

**3. Whole-project attach fails on public data, both ways (t11).**

* without `billing_project`: the metadata lookup runs **in the data project** and hits
  `Error in non-idempotent operation: Access Denied: Project bigquery-public-data: User
  does not have bigquery.jobs.create permission in project bigquery-public-data.`
* with `billing_project=coreychimpbot`: the jobs do run in the paying project, and then
  the attach dies on the project's contents:
  `Binder Error: Query execution failed: Error in non-idempotent operation: Linked
  dataset bigquery-public-data:crypto_kusama is unlinked.`

The attach sent one `UNION ALL` over every dataset's `INFORMATION_SCHEMA.COLUMNS` (the
log would be megabytes; `bq_debug_show_queries` is off in that scenario on purpose).
Attaching **one dataset** works and is what t10 uses.

**4. The REST query path can mis-map result types (t17).** On
`use_rest_api := true`, a DuckDB projection that names a column twice — `typeof(col)`
next to `col` is the natural way to trip it — reads the wrong type for later columns:

```
Invalid Input Error: Failed to cast value: Unimplemented type for cast (GEOMETRY('OGC:CRS84') -> BIGINT[])
```

The same query on the default Storage path is fine. Workaround: don't self-join the
projection on the REST path; use the Storage path (or `SELECT *`).

**5. Projecting out of a dry-run result crashes DuckDB (t18).**

```
INTERNAL Error: Attempted to access index 2 within vector of size 2
```

`SELECT * FROM bigquery_query(..., dry_run := true)` is fine; naming its columns
(`SELECT total_bytes_processed FROM ...`) kills the process and invalidates the database
for the rest of the session. Read the dry-run row with `SELECT *` only.

**6. `INFORMATION_SCHEMA.JOBS_BY_PROJECT` is not readable with these roles.** The
service account gets `Permission Error: BigQuery Permission Denied` on it (it needs a
resource/metadata-viewer role). `bigquery_jobs('coreychimpbot')` works and is what the
cost scenarios use; it exposes `bytes_processed`, not `bytes_billed` — billing is
`max(10 MiB, bytes_processed)`.

## What this does not establish

* **Not "parity"**. This card measures the transport, not the models: whether a dbt
  model built on BigQuery produces the same rows on DuckDB is the parity harness's job
  (`scripts/parity.py`), and dbt's own BigQuery adapter — not this extension — is what
  `make bq` uses.
* **Only one dataset shape.** `usa_names` (5.5 M rows, 5 columns), `thelook_ecommerce`
  and one `GEOGRAPHY` table. No partitioned/clustered table, no external table, no
  `BYTES`/`JSON`-heavy table, no view or materialized view read through the catalog.
* **3 CPUs, single runs.** The parallelism conclusion is a conclusion about this box;
  the second-resolution timings have ±50% run-to-run variance.
* **Writes are barely characterised.** One `CREATE`/`INSERT`/`DROP` round trip; no
  bulk write, no `bigquery_load`/`bigquery_extract`, no concurrency.
* **GCS is untested here** (Transport B, `EXPORT DATA` to GCS, is a separate card).

## Verdict

Transport A works and is measurable: DuckDB v1.5.5 reads BigQuery through the community
extension with real filter and projection pushdown, exact dry-run cost prediction, and a
faithful type mapping, at ~4.4 s for a full 5.5 M-row / 5-column transfer on 3 CPUs and
~70 MiB of peak RSS. The rough edges are: it is a community extension (no core build),
`SCOPE`/`billing_project` must both be right, whole-project attach does not work against
public data, the REST path (and dry-run projection) has two reproducible bugs, and the
write path is slow and needs the table to pre-exist. For a dbt project the honest reading
is that this is a good **exploration and verification** path, not a production query
engine — `bigquery_query` jobs are what a real pipeline would use.
