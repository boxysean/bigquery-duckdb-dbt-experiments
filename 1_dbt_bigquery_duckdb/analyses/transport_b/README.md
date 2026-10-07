# Transport B: `EXPORT DATA` to GCS as Parquet and back, measured

The file-based transport: BigQuery writes Parquet to Cloud Storage with `EXPORT DATA`,
DuckDB reads those objects back, and the reverse direction writes Parquet from DuckDB and
loads it into BigQuery. This directory is the measurement of that path. Every number below
has a scenario file, a log with the raw output, and a command that reproduces it.

* harness: `scripts/transport_b_measure.py`
* scenarios: `analyses/transport_b/sql/*.sql` (one DuckDB process or one BigQuery job each)
* raw output: `analyses/transport_b/logs/*.log` (stdout + stderr + the exact SQL as run)
* generated tables: `analyses/transport_b/results.md`, machine-readable `results.json`

Run of record: **2026-09-27 16:27:31 UTC**, DuckDB **v1.5.5 (Variegata) d8cdaa33fd**,
3 CPUs, billing/quota project `coreychimpbot`, bucket
`gs://coreychimpbot-experiments/transport_b/`, service account
`coreychimpbot@coreychimpbot.iam.gserviceaccount.com`, bigquery extension build `27d85ad`.
44 scenarios, none with an unexpected outcome. The suite was run end to end four times
(three while the scenarios and the harness were being shaken out, then the run of record
whose numbers the generated files carry).

## Reproduce

```
export BQ_KEYFILE=/path/to/service-account.json   # the box's path is in the team runbook
python3 scripts/transport_b_measure.py            # the whole suite, ~7 minutes
python3 scripts/transport_b_measure.py --only b18 b18b b24   # a few scenarios
python3 scripts/transport_b_measure.py --list
```

or, the same thing, `make transport-b`. The suite needs the BigQuery credentials (`BQ_KEYFILE`
must be exported: the harness has no default path, for the same reason
`scripts/transport_a_measure.py` has none — a home directory path does not belong in the
repo), a GCS bucket the account can write objects to in the **same location** as the data,
and it costs money (the run of record: 16.6 GB processed, $0.049 at list price — see "Cost"
below). It cleans up after itself: `b31` deletes every object it wrote under the run's
prefix and drops the probe tables, leaving the bucket and `experiments_dev` as it found them.

`--only` does not throw the rest of the record away: `results.json` merges by scenario key,
so a single scenario can be re-run without losing the other 42 rows (the `runs` list in
`results.json` records which run contributed what).

The key path is substituted into the `.sql` files at run time (placeholder `__SA_PATH__`),
and the bearer token that the DuckDB read path needs is substituted as `__TOKEN__` and
scrubbed: no scenario file or log contains either value. Wall time is measured around the
BigQuery job or the DuckDB process; peak RSS is `/usr/bin/time -v` for that process.

## Results

`analyses/transport_b/results.md` is the generated table for all 43 scenarios. What follows
is the same measurement grouped by the question each scenario answers.

### The read path: what actually gets Parquet into DuckDB (b06–b11, b03b)

| route | result |
|---|---|
| `read_parquet('gs://bucket/obj.parquet')`, no secret (b06) | **fails**: `HTTP Error: HTTP GET error reading 'gs://…' in region '' (HTTP 403 Forbidden)`, `AccessDenied: Access denied.` … `No credentials are provided.` |
| the same with a `TYPE gcs` secret holding placeholder HMAC keys (b06b) | **fails**: this box has no HMAC keys, so there is nothing real to put in it |
| `CREATE SECRET (TYPE http, BEARER_TOKEN '<oauth token>')` + `read_parquet('https://storage.googleapis.com/bucket/obj.parquet')` (b07) | **works**: the mart summed in **1.42 s, 40 MiB** |
| the same secret with `SCOPE` set (b07b) | **fails**: the credential is not applied to the request |
| no secret at all / a bogus token (b07c, b07d) | **fails** (403) — so b07's success is the token, not anonymous access |
| `read_parquet('https://…/*.parquet')` (b08, b08b) | **fails**: `Invalid Input Error: Globs (`*`) for generic HTTP file is are not supported.` `SET allow_asterisks_in_http_paths = true` only silences that message; the literal `*.parquet` path then 404s |

So on a machine without GCS HMAC keys the `gs://` form of the card's premise is unavailable,
and the working route is the GCS **XML API object URL** with an OAuth bearer token on an
**unscoped** `http` secret. Wildcards do not glob on generic HTTP, so a multi-file export
must be handed to DuckDB as an explicit URL list: b09 read all **59** objects of the b04
export — **58,937,715 rows** — as one `read_parquet([...])` in **20.73 s at 50 MiB**.

The alternative is to pull the objects down with the GCS JSON API and read the local copies
(b10): **1,361,557,716 bytes in 186.55 s** (median 3.03 s per object, sequential), then a
0.41 s local read. 21 s versus 187 s — the direct HTTPS read is ~9× faster on this box, and
it never touches the disk.

**Head-to-head with Transport A** (b03/b03b), on the table card 5 used,
`bigquery-public-data.usa_names.usa_1910_2013` (5,552,452 rows):

| | Transport A (extension, Storage Read API) | Transport B (EXPORT DATA + DuckDB read) |
|---|---|---|
| wall | **11.7 s** (11.2 / 11.9 / 22.2 s across four runs) | 3.25 s export (6 files, 18.6 MB) + **3.12 s** read = ~6.4 s |
| peak RSS | 120 MiB | 45 MiB |
| bytes the account is charged for | 111,049,040 (Storage Read API, $1.1/TiB) | 171,432,506 processed / 171,966,464 billed (query, $6.25/TiB) |
| artifact left behind | none | 6 objects, 18.6 MB, until something deletes them |

The split is at ~1 M rows per file (b03b: 6 files, 924,971–925,837 rows each), which is why
the usa_names export is 3.1 MB per file while the 8 GB citibike export is 22 MB per file.

### The documented limits, demonstrated (b04, b05, b19–b21, b13c, b14, b22–b25)

| # | what the card asked | what was measured |
|---|---|---|
| b04 | the 1 GB-per-file limit and the wildcard on a table big enough to split | an **8.0 GB** table (`new_york.citibike_trips_2013`) → **59 files**, 1.36 GB total, **max 27,112,967 bytes**, median 22,172,925 — the cap is never approached because the shard size is set by input parallelism (~1 M rows per file), not by the 1 GiB limit |
| b05 | — | the dry run for b04's shape predicts **8,025,119,188 bytes**, exactly what the real job processed; a dry run is the cheap way to price an export |
| b19 | one table per extract job | two `EXPORT DATA` statements in **one request** are accepted as an implicit script and run as **two child jobs**, each with its own 10 MiB billing floor (20,971,520 bytes billed for 661,896 processed) |
| b20 | the same, spelled as a script | `BEGIN … END` with two `EXPORT DATA` statements: two prefixes, two files, two jobs |
| b21 | the wrong workaround | one `EXPORT DATA` … `UNION ALL` statement writing two tables' rows into **one** file set: one table shape comes out, not two |
| b25 | — | the extension's `bigquery_extract` takes `source_table`, not a query (`[project_or_catalog, billing_project, api_endpoint, …, destination_uris, location, source_table]`), so it can only ever extract one table and cannot carry an `ORDER BY` |
| b14 | the refusal to export nested/repeated data to CSV | **fails**, file count 0: `Error while reading data, error message: Only simple types may be exported as CSV but variable has type ARRAY<INT64>` |
| b13c | (found while building the type table) | **JSON to Parquet is refused too**: `Error while reading data, error message: Type JSON is not currently supported for parquet exports.` — a limit the export-limitations page does not list |
| b14b | the control for b13c | the same JSON table exports to **CSV** fine, so the refusal is about Parquet, not about JSON |
| b13/b18 | nested/repeated data to Parquet | works, one file, every type family preserved (see "Type fidelity") |

### Row order: what "not guaranteed without ORDER BY" actually looks like (b22–b24)

Four exports of the same `SELECT stn, year, mo, da, temp … WHERE temp IS NOT NULL` over
`noaa_gsod.gsod2023` (4,038,747 rows): **three with no `ORDER BY`** (b22, b22b, b22c — the
same SQL three times) and one with `ORDER BY temp` (b23). Every file is read back with one
thread and `preserve_insertion_order=true`, so DuckDB hands the file's physical row order
back unchanged. From b24:

| run (no `ORDER BY`) | file 0 | file 1 |
|---|---|---|
| A (b22) | 237,833 rows · `4cb29205…` | 238,054 rows · `d28275cb…` |
| B (b22b) | **238,054 rows · `d28275cb…`** | **237,833 rows · `4cb29205…`** |
| D (b22c) | 237,833 rows · `4cb29205…` | 238,054 rows · `d28275cb…` |
| `ORDER BY temp` (b23) | **4,038,747 rows · `f0bc98d9…`** (one file, all of it) | — |

The md5s are the fingerprint of the `temp` sequence in physical file order. Runs A and D
produced the same two chunks in the same two files; **run B produced the same two chunks in
the opposite order** — file 0 of B is byte-for-byte the chunk that was file 1 of A, and vice
versa. Same data, same SQL, same wildcard, different file set. Row order inside a file is
storage order, not sorted order: `temp` decreases **118,548 times** within file 0 of A (and
118,548 / 118,400 in D / B, once per file boundary). Only `ORDER BY` makes the artifact
reproducible — `0` decreases, first value the global minimum (−114.3 against −99.3 in the
unordered file) — and it collapses the export to **one file** (11.69 MB against 17 files and
14.97 MB unordered; the sorted file also compresses better).

So the practical rule: without `ORDER BY` you may read the right rows and still get a
different artifact, including the same rows in different files — and a consumer that keys off
file order (a "first file" or "last file", or a per-file merge) is reading a coincidence.
`ORDER BY` buys reproducibility at the cost of the parallelism that produced 17 files.

### Type fidelity via files (b12, b13, b13b, b15–b18, b17b)

`transport_b_types` carries every type family; it is read back from Parquet in b18 and from
CSV in b15/b17. DuckDB's own `DESCRIBE` of the two reads is the evidence:

| BigQuery type | as Parquet (b18) | as CSV (b17) |
|---|---|---|
| `INT64` (9,007,199,254,740,993 = 2^53+1) | `bigint`, exact | `BIGINT`, exact |
| `FLOAT64` | `double` | `DOUBLE` |
| `NUMERIC` (29 digits, 9 of scale) | **`decimal(38,9)`, exact** — `12345678901234567890123456789.123456789` | **`DOUBLE`** — `1.2345678901234568e+28`, 17 digits |
| `NUMERIC` (−0.000000001) | `decimal(38,9)`, exact | `DOUBLE`, `-1e-09` |
| `STRING` (non-ASCII) | `varchar`, intact | `VARCHAR`, intact |
| `BYTES` | `blob` | `VARCHAR` |
| `BOOL` / `DATE` / `DATETIME` / `TIMESTAMP` | `boolean` / `date` / `timestamp` / `timestamp` | `BOOLEAN` / `DATE` / `TIMESTAMP` / `TIMESTAMP` |
| `TIME` | **`time with time zone`** (a zone-less type that acquires one) | `TIME` |
| `ARRAY<INT64>`, `ARRAY<STRING>` | `bigint[]`, `varchar[]` | refused (b14) |
| `STRUCT`, `ARRAY<STRUCT>`, nested struct-of-struct[] | `struct(a bigint, b varchar)`, `struct(x,y)[]`, `struct(inner_list struct(z)[])` | refused (b14) |
| `JSON` | **refused** (b13c) | `VARCHAR` with canonicalised text: `{"a":[1,2],"k":1,"s":"héllo"}` (b17b) |
| `BIGNUMERIC` (b13b/b18b) | **`double`** — `1.234567890123457e+37`, 16 significant digits of 38, **no error** | `DOUBLE`, same narrowing |
| `GEOGRAPHY` (b13b/b18b) | DuckDB's native `geometry`, `POINT (-122.40000000000002 37.7)` — note the coordinate text is not character-identical to the input | `DOUBLE`-style text |

Two results here correct the card's premise. Parquet does **not** round-trip every BigQuery
type family identically: `NUMERIC` is exact at `DECIMAL(38,9)`, but **`BIGNUMERIC` silently
becomes a `double`** (16 significant digits out of 38, no error, no warning), and a NULL
array comes back as an **empty list** rather than NULL (`[]` for a row whose array was NULL;
a NULL struct stays NULL). CSV's degradation is as expected — `NUMERIC`/`BIGNUMERIC` become
`DOUBLE`, `BYTES` becomes text — but CSV keeps `DATE` and `TIMESTAMP` exactly, and on the
one-row flat table it is 14× smaller than Parquet (304 bytes versus 4,255). Parquet wins on
real data: 4.04 M rows is 14.97 MB.

### The reverse direction: DuckDB writes Parquet, BigQuery loads it (b26–b29)

DuckDB writes a 1,000-row table containing `DECIMAL(38,9)` (Parquet `FIXED_LEN_BYTE_ARRAY`
with the DECIMAL(38,9) logical type), `DOUBLE`, `VARCHAR` (non-ASCII), `BOOLEAN`, `DATE`,
`TIMESTAMP` (`isAdjustedToUTC=false`), `TIMESTAMPTZ` (`true`), `BLOB`, `LIST<INT64>`,
`STRUCT`, `LIST<STRUCT>`. It is loaded twice — once by this harness' own upload +
`jobs.insert` (b27), once by the extension's `bigquery_load` (b28) — and both tables get the
same declared schema:

| DuckDB column | BigQuery type after the load |
|---|---|
| `DECIMAL(38,9)` | `NUMERIC` (the same 38/9) |
| `DOUBLE` | `FLOAT64` |
| `VARCHAR` / `BOOLEAN` / `DATE` / `BLOB` | `STRING` / `BOOLEAN` / `DATE` / `BYTES` |
| `TIMESTAMP` (zone-less) **and** `TIMESTAMPTZ` | **`TIMESTAMP`** — both; the zone-less/zoned distinction is lost |
| `LIST<INT64>` | **`RECORD`** (`RECORD<list ARRAY<RECORD<element INT64>>>`), not `ARRAY<INT64>` |
| `STRUCT` / `LIST<STRUCT>` | `RECORD(a,b)` / `RECORD` |

b29 compares all 1,000 rows, every column, against the dump DuckDB wrote — parsing the
values rather than string-matching them: **0 mismatches, both tables** (the 29-digit
`DECIMAL(38,9)`, the non-ASCII text, the timestamps as instants, the arrays unwrapped). The
one caveat is the list shape: `arr_i[OFFSET(0)]` on the loaded table returns the whole
3-element list rather than the first element (`1`); `arr_i.list[OFFSET(0)].element` returns
`1`. SQL written against a native `ARRAY<INT64>` column does not run the same against a
column that arrived in a Parquet file.

Also measured while doing it: `bigquery_load`'s destination is the **second positional**
argument (`bigquery_load('project', 'dataset.table', source_table := 't')`); passing it as
`destination_table :=` does not bind (`No function matches the given name and argument types
'bigquery_load(VARCHAR)'`), and the destination string must be `dataset.table`, not
`project.dataset.table`.

### Cost (b30, from the job statistics of this run and Google's price pages)

| | value |
|---|---|
| jobs in the run | 19, of which 15 `EXPORT DATA` |
| bytes processed | 16,718,523,210 (16.7 GB) |
| bytes **billed** | 8,820,621,312 (8.82 GB) |
| objects / bytes written to GCS (peak, before cleanup) | 190 objects, 2,799,846,857 bytes (2.80 GB) |
| list price for this run | **$0.0501** at $6.25/TiB on-demand |
| real invoice impact | $0 inside the 1 TiB/month free tier, unless the account's shared allowance is already spent |
| storage if the objects are left | $0.068/month at $0.026/GiB-month |
| egress if the whole export is read to this box | $0.31 at $0.12/GiB |

Three pricing facts the statistics make concrete. First, **the 10 MiB minimum per statement
dominates small exports**: the 287 KB mart (b02) is billed 10,485,760 bytes, 36× its size,
and every one-row type-table export is billed the same 10 MiB. Second, **the extract job is
free but `EXPORT DATA` is not**: b25's `bigquery_extract` scanned the same 8,025,119,188
bytes as b04's `EXPORT DATA` and contributed **nothing** to bytes billed, while b04's
`EXPORT DATA` billed all 8.0 GB as a query — the extension's forward path is the cheaper way
to get the same Parquet into the bucket. Third, **a dry run prices an export exactly** (b05
predicted b04's 8,025,119,188 bytes), so a new export shape can be priced for free.

The comparison numbers come from Google's [BigQuery data-extraction
pricing](https://cloud.google.com/bigquery/pricing#data-extraction) and [Cloud Storage
pricing](https://cloud.google.com/storage/pricing), read 2026-09-27, and are recorded in
`results.json` under `pricing_constants`. The Storage Read API that Transport A uses is
$1.1/TiB with 300 TiB/month free — 5.7× the query rate, which is the other half of the cost
comparison.

### Failure modes seen (with the real text)

1. `read_parquet('gs://…')` with no credentials — `AccessDenied: Access denied. … No credentials are provided.` (b06).
2. `TYPE gcs` secret — unusable here; the box has no HMAC keys to put in it (b06b).
3. A `SCOPE`d `http` secret does not apply its bearer token to the request (b07b).
4. `*` on a generic HTTP path — `Globs (`*`) for generic HTTP file is are not supported.`; the suggested flag only silences it, the path then 404s (b08, b08b).
5. Nested/repeated → CSV — `Only simple types may be exported as CSV but variable has type ARRAY<INT64>` (b14).
6. `JSON` → Parquet — `Type JSON is not currently supported for parquet exports.` (b13c), a limit the docs do not list.
7. `bigquery_load` with a named `destination_table` — `No function matches the given name and argument types 'bigquery_load(VARCHAR)'` (b28; the destination is positional).
8. The GCS JSON API `DELETE …/o/<name>` needs the object name URL-encoded (slashes as `%2F`) or every delete 404s (hit while cleaning the bucket by hand, not by a scenario).

## When the file path beats the direct path, and when it does not

Written against the measured numbers above, and against Transport A's (`analyses/transport_a/`).

**The file path wins when**

* **the read is scheduled or repeated.** One export, many readers: the 8 GB export cost
  8.0 GB of billed query once (b04) and then every DuckDB reader — or Spark, or Pandas —
  reads the same 59 objects with no BigQuery participation at all, no Storage API session,
  no per-read bytes. Transport A pays 111 MB of Storage Read API traffic *per read* of the
  5.5 M-row table (t04/t07).
* **the consumer must not depend on BigQuery.** A Parquet object needs a GCS credential and
  nothing else — no `bigquery` extension, no community build to pin (Transport A requires
  build `27d85ad`; the core repo 404s on this version). DuckDB read the export in 3.12 s at
  45 MiB against Transport A's 120 MiB.
* **the pipeline is dbt-native and declarative.** `EXPORT DATA` is plain SQL: it belongs in
  a model, a post-hook or a scheduled query, and it composes with `ORDER BY` for a
  reproducible artifact (b23). `bigquery_extract` cannot express either — it takes a table
  name, not a query (b25).
* **the data is large and read many times, or read by something that cannot stream.** 20.73 s
  to read 58.9 M rows over HTTPS (b09), against a Storage Read API path that must be
  implemented per engine.
* **the data must cross an engine boundary.** The file is the boundary: DuckDB writes
  Parquet, BigQuery loads it, values verified 1,000/1,000 (b26–b29).

**The direct path wins when**

* **the read is interactive or latency-sensitive.** Transport A materialized 5.5 M rows in
  11.7 s, once, from cold — no export job to wait for, no file lifecycle, no bucket in the
  path. Transport B's 8.4 s for the same table is only faster if the export has already run.
* **the data must be fresh.** A file is a snapshot: it carries the cost of a job and the age
  of a job. A direct read is the current table.
* **the read is selective.** The extension pushes filters and projections into BigQuery
  (`BigQuery row restrictions: …`), so `WHERE state = 'CA'` reads 95,373 rows. A Parquet
  file must be read whole, and a wildcard read has no pruning at all — you pay for every
  object in the list.
* **the query is small.** The 10 MiB per-statement billing floor (b02) means a small export
  costs 36× its own size, while a direct read of a few thousand rows costs a few thousand
  rows.
* **the type is `BIGNUMERIC`.** Files silently drop it to a `double` (b18b). A BIGNUMERIC
  column must either be read directly or be cast in the export — the file path cannot carry
  it, and it will not tell you.

**The measured crossover**: a first cold read of the same 5.5 M-row table costs Transport A
11.7 s / 120 MiB / 111 MB charged and Transport B 3.25 s export + 3.12 s read / 45 MiB / 171 MB
charged; from the second read onward Transport A pays the same again and Transport B pays the
GCS egress only ($0.12/GiB — 1.36 GB of Parquet is $0.16 to pull to this box). The file path
is a **cache**, and it is worth exactly as many reads as the snapshot gets.

## What is verified, and what is not

Verified end to end on this box: the export, the read over the GCS XML API, the wildcard and
1 GB behaviour, the single-table rules, the CSV and JSON refusals, the row-order behaviour,
type fidelity for every type family in the probe table, the reverse load by both routes with
a full value comparison, and the cost accounting from the job statistics.

Not verified, and why:

* **HMAC-key reads (`gs://…`, `TYPE gcs`)**: no HMAC keys exist on this box, so the form the
  card names was exercised only as a failure (b06, b06b). The bearer-token route is measured
  instead, and it is the one the extension's own `bigquery_load` uses.
* **A cross-location bucket** (the trap that bit an earlier attempt): the bucket and the
  dataset are both `US` here, so the location rule is not re-measured; the failure mode is
  recorded in the card thread, not reproduced in a scenario.
* **The 1 GiB file cap as an observed limit**: the largest file seen is 27 MB, because shard
  size is driven by input parallelism. The cap is documented, not hit.
* **Parallel reads of many objects**: b09 is DuckDB's default single-process read of 59
  objects (27.14 s). A distributed reader, or DuckDB's own parallelism, was not tested.
* **`BIGNUMERIC` beyond 16 digits**: the narrowing is measured; whether any export option
  avoids it (AVRO was not tested) is not.
