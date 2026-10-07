# NOTES — BigQuery + Spark project (card t_379e9e7b)

Orchestrator notes. This file records what was **measured on this box** before any
implementation code was written, so the next run resumes instead of re-deriving it.

## Status

**Blocked before implementation.** Claude Code (the only permitted writer of application
code, per the standing house rule) is out of its account-wide session window:

```
claude -p "Reply with exactly: PROBE-OK" --model opus --max-turns 1 --output-format json
  -> is_error: true, api_error_status: 429, terminal_reason: api_error
  -> "You've hit your session limit · resets 6:50pm (Europe/Vienna)"
same command with --fallback-model haiku -> identical 429
```

Measured at 2026-10-06 15:26 CEST; reset 18:50 Europe/Vienna (204 minutes away). The limit is
account-wide and shared with the owner, so it is not attributable to this card alone.

`SPEC.md` in this directory is the finished design contract and is authoritative for the
implementation. Nothing in it is guesswork: every environment fact below was measured.

## 1. Spark runtime: what is genuinely available (measured, not assumed)

| question | answer |
|---|---|
| JDK | **not installed** on the box; Temurin 21 installed by us at `~/.local/spark/jdk` |
| Spark | **not installed**; `pyspark==4.2.0` installed by us at `~/.local/spark/venv` |
| Docker / podman | absent — no container route |
| Databricks workspace | none |
| local PySpark in *session* mode | **impossible**: dbt-oss 2.0.5's spark adapter accepts only `thrift`, `http`, `livy`, `spark-connect`; `method: session` is rejected as an unknown variant |
| a real endpoint | **YES — running.** Spark 4.2.0 Spark Thrift Server (HiveServer2) on `127.0.0.1:10000`, started from the pip wheel: `spark-submit --class org.apache.spark.sql.hive.thriftserver.HiveThriftServer2`. `dbt debug` against it: **connection test OK (18.8s)** |

So Spark is **not** compile-only here: the models can really execute. `scripts/start_spark.sh`
must reproduce this (JDK + pyspark + thrift server).

### dbt facts that shape the whole project

* `DBT_ALLOW_EXPERIMENTAL_ADAPTERS=true` is **required**; without it every command fails with
  `InvalidConfig (dbt1005): The 'spark' adapter is not yet supported by dbt. Supported
  adapters: snowflake, bigquery, databricks, redshift, duckdb, salesforce, clickhouse.`
* The spark profile needs `user:` — `'user' is required when auth is 'PLAIN' or 'NONE'`.
* Session read back through dbt: `spark_catalog` / `default` / `hermes` / **`UTC`** / `4.2.0`.
* **The adapter cannot fetch ARRAY columns**: `dbt show --inline "select sequence(1,9,3) as s"`
  → `NotImplemented: [spark] Unsupported type ARRAY_TYPE`. Models whose *final* projection
  contains no array are unaffected; anything that returns an array to the client fails.

## 2. Spark SQL behaviour, measured through dbt against the real endpoint

| construct | result |
|---|---|
| `select * except (b) from (...)` | **works** — Spark 4.2 accepts the BigQuery spelling |
| `select * exclude (b)` | parse error (DuckDB spelling) |
| `unnest(...)` in FROM | **fails** — `UNRESOLVABLE_TABLE_VALUED_FUNCTION: Could not resolve unnest` |
| `explode(arr)` in a subquery | works |
| `lateral view explode(arr) v as x` | works |
| `struct(1 as a, 2 as b)`, `s.a` | works — identical to BigQuery |
| `date_trunc('week'\|'quarter'\|'month', ts)` | Monday / 2024-01-01 / 2024-03-01 — week is already Monday |
| `timestamp_trunc(...)` | no such function (BigQuery-only) |
| `(dayofweek(d) + 5) % 7 + 1` | Fri 5, Sun 7, Mon 1 — the BigQuery shift, unchanged |
| `date_format(d, 'yyyy/MM/dd')` | works; **Java patterns**, not strftime (`'%Y/%m/%d'` raises `INCONSISTENT_BEHAVIOR_CROSS_VERSION`) |
| `unix_micros(e) - unix_micros(s)` | `90.5` |
| `unix_timestamp(e) - unix_timestamp(s)` | `90.0` — **drops sub-second precision** |
| `try_cast('nope' as bigint)` | NULL |
| `try_divide(1.0, 0.0)` / `try_divide(1.0, 4.0)` | NULL / 0.25 |
| `regexp_like(x, p)`, `x rlike p` | both work |
| `md5(concat_ws('\|\|', '1', 'x'))` | `df6729622b8fb993f31b1ba95a27e5cc` — **identical to the root project's DuckDB self-check value** |
| `cast(1 as decimal(39,2))` | **fails** — `DECIMAL_PRECISION_EXCEEDS_MAX_PRECISION: Decimal precision 39 exceeds max precision 38` |
| `typeof(...)` | `bigint`, `string`, `double`, `timestamp`, `decimal(18,2)`, `decimal(38,9)`, `array<bigint>` |
| `cast(timestamp'...' as string)` | `2024-03-15T13:45:00Z` — an instant, rendered UTC |

## 3. Data scale (from the root project's committed loader log)

The real `bigquery-public-data.thelook_ecommerce` tables are small enough to pull to this box:

| table | rows | bytes |
|---|---|---|
| distribution_centers | 10 | 809 |
| products | 29,120 | 4.3 MB |
| users | 100,000 | 19.8 MB |
| orders | 124,952 | 6.7 MB |
| order_items | 181,313 | 13.6 MB |
| inventory_items | 489,625 | 81.2 MB |
| events | 2,425,698 | 385.3 MB |

`~/.config/gcp/coreychimpbot-sa.json` (mode 600, outside the repo) is present, so the BigQuery
leg is real, not compile-only. **Never fake a BigQuery run.**

## 4. Decisions taken (full reasoning in `SPEC.md`)

* New folder **`bigquery_spark/`**, a sibling of the root project — a peer two-engine project,
  not an example; its own `dbt_project.yml`/`profiles.yml` leave the root project's guardrail
  and its `models/`+`analyses/` portability scan untouched.
* Two targets only: `spark` and `bigquery`. **No DuckDB anywhere.**
* `default__` = Spark, `bigquery__` = BigQuery, dispatch namespace `bq_spark_experiments`.
* The **same real rows** feed both legs (Spark via local Parquet pulled from BigQuery, BigQuery
  straight from the public dataset), so `--same-data` value parity is the default mode — the
  analogue of the root project's `make value-parity`.
* `unnest` in FROM becomes a **FROM-clause fragment macro** (`explode_array_rows`), because
  Spark has no `unnest` table-valued function — the one place the root project's recorded
  "do not wrap unnest" rule breaks.
* `except_columns` keeps both branches rendering `* except (...)` — measured to work on Spark.
* The **decimal guard**: Spark `DECIMAL` caps at precision 38 (measured by execution), BigQuery
  reaches `BIGNUMERIC` at 76.76 digits; `decimal_type(p, s)` must raise on Spark above 38 and
  never silently fall back to `double`.
* Timezone: the Spark session is pinned to UTC and that is **proved in a self-check**; a
  non-UTC session must be measured and reported, not hidden.

## 5. What the next run should do

1. `bash bigquery_spark/scripts/start_spark.sh` (or the installed service) — confirm the
   endpoint is up on `127.0.0.1:10000`; `dbt debug` must pass.
2. Implement `SPEC.md` with Claude Code on Opus, in **several small phases** (skeleton+macros;
   loaders; gate+parity; docs), verifying between phases.
3. Deliver: `docs/bigquery-to-spark.md` (the catalogue), `docs/conclusion.md`, README,
   the portability gate output, and the value-parity result — including whether the predicted
   Spark-vs-BigQuery **money** difference appears.

## 6. Phase 1 done (2026-10-06): skeleton + macros + models (SPEC sections 1, 2, 3)

Written: `dbt_project.yml`, `profiles.yml` (spark default + bigquery), `packages.yml`,
`macros/polyglot/` (10 files), `models/`, `tests/`, `analyses/polyglot_showcase.sql`.
Verified: `dbt compile --target spark` exit 0 and `--target bigquery` exit 0 (29 models, 167
tests, 1 analysis); `dbt run-operation polyglot_selfcheck --target spark` exit 0:
**54 ok, 1 skipped by name, 0 failed of 55**. Models NOT built yet (next phase).

### Model files changed, and why

| file | change | kind |
|---|---|---|
| `models/marts/dim_date.sql` | `cross join unnest(...) as {{ unnest_alias('date_day') }}` -> `{{ explode_array_rows(generate_date_series('first_date', 'last_date'), 'date_day') }}` | **SQL: the one required divergence** (Spark has no `unnest`) |
| `models/intermediate/int_orders__item_rollup.sql` | header comment: dropped "(none in the fixture)" | comment only |
| `models/staging/_thelook__sources.yml` | header comment + source description: DuckDB/fixture wording -> Spark | docs only; the `database:` expression is unchanged |
| `models/staging/_thelook__models.yml`, `models/intermediate/_int__models.yml`, `models/marts/_marts__models.yml` | "decimal(18,2) on DuckDB" -> "on Spark" (marts also "double on ...") | comment only |
| `models/marts/.gitkeep` | "BigQuery and DuckDB" -> "BigQuery and Spark" | comment only |
| `tests/assert_order_item_created_at_is_plausible.sql` | trailing comment about the DuckDB fixture -> both legs read the same real rows | comment only |

The comment-only edits exist because the card forbids the word DuckDB anywhere in this tree;
none of them changes rendered SQL.

**Counts:** 29 model `.sql` files: **28 have SQL identical to the root project**; 27 are
byte-for-byte identical, 1 differs only in a comment, 1 (`dim_date.sql`) needed a SQL change.
Of all 36 files under `models/`, 29 are byte-for-byte identical. All 4 tests have identical SQL
(1 comment edit).

`analyses/polyglot_showcase.sql`: the one `(select count(*) from unnest(...) as n)` became
`(select count(*) from (select 1 as one) as base {{ explode_array_rows(generate_series(1, 5), 'n') }})`
(measured: the `unnest` form fails on Spark, the lateral-view form returns 5).

### New measurements this phase (Spark 4.2.0, via beeline against 127.0.0.1:10000)

| construct | result | consequence |
|---|---|---|
| `interval 1 quarter` | **PARSE_SYNTAX_ERROR** | Spark branch of `generate_date_series` renders a quarter step as `interval 3n month` |
| `sequence(date '2024-01-31', date '2024-04-30', interval 1 month)` | `[01-31, 02-29, 03-31, 04-30]` | steps from the start, no month-end drift |
| `sequence(1, 0)` / `sequence(5, 1)` | `[1, 0]` / `[5, 4, 3, 2, 1]` (counts down) | BigQuery `generate_array(1, 0)` is empty: start > stop diverges; documented on the macro |
| `sequence(1, 0, 1)`, date sequence with start > stop | raises `Illegal sequence boundaries` | same |
| `explode(array())` in a lateral view | 0 rows | same outer-row-dropping as BigQuery `cross join unnest([])` |
| `md5(concat_ws('\|\|', 1, 'x'))` (integer arg) | `df6729...e5cc` | Spark surrogate key needs no cast; `[month_number(ts), 7]` = md5('202403\|\|7') = `a480dd56...fc0a` (matches Python) |
| `md5(concat_ws('\|\|', 1, null))` | = md5('1') | concat_ws SKIPS null; BigQuery concat returns NULL |
| `cast(x as decimal)` | `decimal(10,0)` | why money is pinned to decimal(18,2) |
| `cast(1.005 as decimal(18,2))` | `1.01` | exact-to-scale rounding (the money prediction's mechanism) |
| `cast(<array> as string)` | `[1, 4, 7]` | the self-check casts every value to STRING in SQL, so array cases run even though the adapter cannot fetch ARRAY |
| `date_trunc('month', date '...')` | typeof `timestamp` | `month_start` needs no cast on Spark |

**Non-UTC session (the timezone gotcha), measured** in a separate beeline session with
`set spark.sql.session.timeZone=Europe/Vienna` (the SET did not leak: a new session read back `UTC`):

| expression | UTC session | Vienna session |
|---|---|---|
| `cast(timestamp '2024-03-15 13:45:00+02:00' as string)` | `2024-03-15 11:45:00` | `2024-03-15 12:45:00` |
| `unix_micros(timestamp '2024-03-15 13:45:00')` (naive literal) | `1710510300000000` | `1710506700000000` (read as Vienna time, 1 h off) |
| `cast(timestamp '2024-03-15 23:30:00+00:00' as date)` | 2024-03-15 | **2024-03-16** |
| `date_format(timestamp '2024-03-31 23:30:00+00:00', 'yyyy-MM')` | 2024-03 | **2024-04** |

Instants are preserved, but every day/month boundary moves: a non-UTC session would silently
change `order_date`, `dim_date`, the cohort months and the monthly marts. The self-check case
`session time zone is UTC` guards this on every run.

### SPEC deviations / additions

* SPEC 3.3 says Spark `sequence(start, stop, interval n part)` covers the date generator; true
  except for **quarter**, which Spark cannot spell (above). Handled in the macro, not the model.
* The self-check casts values to STRING in SQL, so only ONE Spark case is skipped (the p > 38
  decimal, a compiler error by design). Its failure is captured with
  `dbt run-operation polyglot_render --args '{include_bignumeric: true}' --target spark` -> exit 1
  with the decimal_type message.
* The BigQuery expectations in `polyglot_selfcheck` are written but **not executed in this
  phase** (the BigQuery leg is the next phase's). Typeof cases and array-text cases are skipped
  by name on BigQuery (no `typeof()`; no CAST ARRAY AS STRING); length/element cases through
  `explode_array_rows` cover arrays on both.
* `SPEC.md` and this file still mention DuckDB, as the orchestrator's reference to the root
  project; nothing else in the tree does (generated `logs/` aside).

## 7. Phase 2 done (2026-10-06): scripts + Makefile (SPEC sections 2, 4, 5)

Written: `scripts/{install_prereqs.sh, start_spark.sh, stop_spark.sh, check_env.sh,
load_spark_sources.py, check_portability.py}`, `Makefile`. Not yet: `parity.py`,
`spark_check.sh`, `pre_pr.sh` (the Makefile already references `parity.py` / `pre_pr.sh`).

Verified: `check_env.sh` exit 0 (exit 1 without `DBT_ALLOW_EXPERIMENTAL_ADAPTERS`);
`check_portability.py` exit 0 (30 files, 0/13, 0/12, 0 target-branch, PORTABLE); `--demo`
exit 0; loader `--tables distribution_centers,orders` exit 0 (10 and 124,650 rows = numRows =
Spark count; 4 timestamp columns, no instant moved; session UTC); loader with no credential
exit 2; `start_spark.sh` reports the running server (pid 637350) and starts nothing; a scratch
server (`SPARK_PORT=10001 SPARK_STATE_DIR=/tmp/...`) started in 26 s, read back UTC/4.2.0, and
`stop_spark.sh` stopped it. `make bq` with no credential exits 2. The heavy tables, `dbt build`
and `install_prereqs.sh`'s download branch (everything was already installed) were NOT run.

### SPEC deviations, all measured

* **SPEC 5 `CREATE OR REPLACE TABLE ... USING PARQUET` fails on Spark 4.2.0's session catalog:**
  `UNSUPPORTED_FEATURE.TABLE_OPERATION ... does not support REPLACE TABLE`. The loader uses
  `DROP TABLE IF EXISTS` + `CREATE TABLE ... USING PARQUET LOCATION` (external: the drop
  keeps the files, measured).
* **SPEC 4 Spark-only token list: two seed tokens are valid BigQuery** (dry run, 0 bytes):
  `unix_micros(` (BigQuery has `UNIX_MICROS`) and `array<bigint>` (`BIGINT` is an INT64
  alias). Both dropped; the list has 12 tokens. All 13 BigQuery-only tokens were rejected by
  Spark. Spark 4.2 does have its own `date_diff(end, start)` / `date_diff(unit, start, end)`
  (both return 4); the BigQuery form `date_diff(a, b, day)` fails (`UNRESOLVED_COLUMN`), and
  the Spark branch spells it `datediff`, so the token stays.
* The Spark adapter renders sources **two-part** (`` `thelook_ecommerce`.`orders` ``), so
  `spark_catalog` never appears in the Spark render either; the loader registers into the
  `thelook_ecommerce` database of the session catalog to match.
* The BigQuery client was not installed anywhere; `install_prereqs.sh` puts it (with the
  Storage Read API client and pyarrow) in `~/.local/spark/venv`, beside pyspark.
* SPEC 2 says `install_prereqs.sh` also starts the endpoint; it does not (`start_spark.sh`
  does, and `make spark` runs it).

### Risk for the parity phase: the public dataset changes over time

`orders` read **124,650** rows on 2026-10-06 (BigQuery `numRows`), against 124,952 in the
older loader log quoted in section 3, and the timestamps run into the future (max
`returned_at` 2026-10-15). The BigQuery leg reads the live table and the Spark leg reads a
snapshot, so same-data parity only holds if both are read close together. Re-load before
comparing, and compare row counts first.

## 8. Workspace hygiene

The root project is untouched: only `bigquery_spark/` was added, and `git -C .. status` shows
no modification to the root project's tracked files.

## 9. Run 2026-10-06 21:32–23:4x CEST: endpoint restarted, every gate re-measured

Status of this run: **the endpoint is back, the sources are loaded, both builds and every
two-target gate pass; the parity harness's own self-check fails on one line and Claude Code
is out of its session window, so the fix and the docs are the next run's work.** Nothing was
merged; `main` is untouched.

### What ran, with the real output

```
$ make check-env                                        -> exit 0, 9 checks ok
    (dbt-oss 2.0.5, DBT_ALLOW_EXPERIMENTAL_ADAPTERS, JDK 21, pyspark 4.2.0,
     google-cloud-bigquery 3.46.1 + pyarrow 25.0.1, endpoint reachable, both ymls,
     BigQuery credential: service-account key file)

$ make load-sources                                     -> exit 0, 87.4s
 table                   BigQuery numRows  rows written  Spark count  status
 distribution_centers                  10            10           10  ok
 products                          29,120        29,120       29,120  ok
 users                            100,000       100,000      100,000  ok
 inventory_items                  487,799       487,799      487,799  ok
 orders                           124,650       124,650      124,650  ok
 order_items                      180,778       180,778      180,778  ok
 events                         2,421,086     2,421,086    2,421,086  ok
 instants moved by the load: none (12 timestamp column(s) checked; Spark session time zone UTC)

$ dbt build --target spark                              -> exit 0  [3m 12s]
    Processed: 29 models | 167 tests
    Summary: 196 total | 195 success | 1 warn
    the one warn is tests/assert_order_item_created_at_is_plausible, severity: warn BY
    DESIGN (the published dataset's jitter, documented in the test's header)

$ dbt build --target bigquery                           -> exit 0  [2m 43s]
    Processed: 29 models | 167 tests
    Summary: 196 total | 195 success | 1 warn   (the same by-design test)

$ python3 scripts/check_portability.py                  -> exit 0
    compiled files checked: 30 (models: 29, analyses: 1)
    BigQuery-only tokens in the Spark render: 0/13
    Spark-only tokens in the BigQuery render: 0/12
    target-branch findings: 0
    PORTABLE

$ python3 scripts/check_portability.py --demo           -> exit 0
    demo: guardrail failed as designed (1 dialect finding(s), 1 target-branch finding(s)
          in _portability_demo.sql) -> NOT PORTABLE: 2 finding(s), then PORTABLE again

$ dbt run-operation polyglot_selfcheck --target spark   -> exit 0  [5.6s]
    selfcheck: 54 ok, 1 skipped by name, 0 failed, of 55 cases on spark
        (skipped: decimal ceiling: decimal_type(77, 38))

$ dbt run-operation polyglot_selfcheck --target bigquery -> exit 0  [1m 21s]
    selfcheck: 34 ok, 21 skipped by name, 0 failed, of 55 cases on bigquery

$ dbt run-operation polyglot_render --args '{include_bignumeric: true}' --target spark
                                                        -> exit 1, as designed:
    [error] [JinjaError (dbt1501)]: decimal_type(77, 38): Spark DECIMAL is capped at
    precision 38 (DECIMAL_PRECISION_EXCEEDS_MAX_PRECISION above it), while BigQuery reaches
    BIGNUMERIC at 76.76 digits of precision (scale 38), which has no Spark equivalent.

$ python3 scripts/parity.py                             -> exit 1  DIGEST SELF-CHECK FAILED
```

Raw logs (untracked by design, in the worktree): `target_load.log`, `target_build_spark.log`,
`target_build_bq.log`, `target_gates.log`, `target_parity.log`.

### The parity self-check bug, fully diagnosed

```
  arr__sum         spark      10119176120   bigquery      13677882513   MISMATCH
```

Every other metric and every type kind matches. Cause, measured with a probe that printed the
per-row canonical text and the per-row md5 on both engines: in `scripts/parity.py`,
`Engine.canon` renders an **array** on BigQuery as
`ARRAY_TO_STRING(ARRAY(SELECT ... FROM UNNEST(<expr>) ...), '|')`. `UNNEST(NULL)` yields zero
rows, so the subquery returns an **empty array** and the value is `''` — indistinguishable from
a genuinely empty array. Spark's `array_join(NULL, '|')` is `NULL`, so `SUM` skips it. The
all-NULL fixture row therefore contributes `md5('') = 3558706393` on BigQuery only, which is
exactly the delta (`13677882513 - 10119176120`). The five non-NULL fixture rows are
byte-identical on both engines.

The harness is right to refuse: the canonicalisation, not the engines, is wrong. The models
are unaffected (no model returns an array to the client). The fix spec is at
`../.spec-parity-null-fix.md`: a NULL guard around the array (and struct) rendering on both
engines, plus one fixture row with a NULL array element.

### Blocked on

Claude Code, the only permitted writer of this project's code, is out of its account-wide
session window (measured twice, 21:54 and 22:12 CEST):

```
claude -p "Reply with exactly: PROBE-OK" --model opus --max-turns 1 --output-format json
  -> is_error: true, api_error_status: 429, terminal_reason: api_error
  -> "You've hit your session limit · resets 11:50pm (Europe/Vienna)"
--fallback-model haiku -> identical 429
```

So this run stops at verified infrastructure + diagnosis; the fix, the value-parity run, the
catalogue and the decision-maker conclusion are the next run's (see `../CHECKPOINT.md`).

## 10. Construct reconnaissance for the catalogue (measured 2026-10-06 22:1x, read-only)

Run by the orchestrator with one probe per construct against the live Spark 4.2.0 Thrift
Server (one beeline session) and the BigQuery REST API (no table reads: 0 bytes billed).
Probe: `/home/hermes/.hermes/profiles/bruno/cache/scratch/probe_constructs.py`.
**Every cell below is what the engine actually answered or actually raised** — not a
prediction. Where a probe could not be made equivalent, it says so.

| construct | BigQuery (live) | Spark 4.2.0 (live) |
|---|---|---|
| `QUALIFY row_number() over (order by a) = 1` | `1 2` (works) | `1 2` — **works, unchanged** (Spark 4.2 accepts QUALIFY; a pleasant surprise, and the reason no model needed a branch here) |
| `SELECT * EXCEPT (b)` | `1` | `1` — works, unchanged |
| `SELECT * REPLACE (3 AS b)` | `1 3` | **PARSE_SYNTAX_ERROR** — no Spark spelling; would need the column list written out |
| array `[OFFSET(0)]` | `10` | **PARSE_SYNTAX_ERROR** |
| array `[ORDINAL(1)]` | `10` | **PARSE_SYNTAX_ERROR** |
| array `[SAFE_OFFSET(5)]` | `None` (null, no error) | **PARSE_SYNTAX_ERROR** |
| `element_at(arr, 1)` | **Function not found** | `10` — one-based; the off-by-one hazard is real and silent |
| `GENERATE_DATE_ARRAY` | `array_length(...)` = 3 | `size(sequence(d, d, interval 1 day))` = 3 — equivalent via `sequence` |
| `GENERATE_ARRAY` | `sum(unnest(generate_array(1,4)))` = 10 | `explode(sequence(1,4))` = 10 — equivalent |
| `PARSE_DATE('%Y-%m-%d', ...)` | `2024-03-15` | `to_date(s, 'yyyy-MM-dd')` = `2024-03-15` |
| `FORMAT_DATE('%Y/%m/%d', ...)` | `2024/03/15` | `date_format(d, 'yyyy/MM/dd')` = `2024/03/15` — **a different pattern language**, not just a different name |
| `EXTRACT(year from date)` | `2024` | `2024` |
| `EXTRACT(week from date '2024-03-15')` | **`10`** | **`11`** — a silent divergence: ISO week vs US week. The project never calls it (verified: `extract(week` appears in no model) |
| `DATE_TRUNC(date, month)` | `2024-03-01` (a DATE) | `date_trunc('month', d)` = `2024-03-01 00:00:00.0` — **a TIMESTAMP**, so the canonical kind moves unless cast back |
| `TIMESTAMP_TRUNC(ts, hour)` | `1.7105076E9` | **UNRESOLVED_ROUTINE** — no `timestamp_trunc`; `date_trunc('hour', ts)` is the Spark form |
| `STRING_AGG(x, ',' ORDER BY x)` | `a,b,c` | `concat_ws(',', sort_array(collect_list(x)))` = `a,b,c` — equivalent, but the ordering clause is a rewrite |
| `APPROX_COUNT_DISTINCT` | `3` | `3` — works, unchanged |
| `ARRAY_AGG(x IGNORE NULLS)` | `2` | `2` — **the Spark probe is NOT an equivalent test** (it used `size(array_agg(x))`, a different semantic); a proper Spark spelling (`filter (where x is not null)`) is **unverified** |
| `ARRAY_AGG(x ORDER BY x LIMIT 2)` | `2` | `2` — same caveat: the Spark probe limited ROWS, not the aggregate. **unverified** |
| `PIVOT (sum(v) for k in (...))` | `1 2` | `1 2` — works, unchanged |
| recursive CTE (`with recursive`) | `3` | `3` — works, unchanged on Spark 4.2 |
| `'1' + 1` | **400: Could not cast literal "1" to type DATE** | `2` — diverge in opposite directions: BigQuery refuses, Spark coerces silently |
| `7 / 2` | `3.5` | `3.5` — no integer division on either |
| `1 + 1.5` | `2.5` | `2.5` |
| `cast(1 as bigint) + cast(2 as numeric/decimal(38,9))` | `3` | `3.00000000` — **the money/scale difference, visible directly**: Spark prints the declared scale, BigQuery the shortest form |
| `cast(datetime ... as timestamp)` vs `cast(ts as timestamp_ntz)` | `1.7105103E9` | `2024-03-15 13:45:00.0` — different types, as the design says |
| `current_timestamp()` | `2026-10-06 20:10:50.209692+00` | `timestamp` (typeof) |
| three-part `` `project.dataset.table` `` | `10` rows | **REQUIRES_SINGLE_PART_NAMESPACE** — Spark's session catalog takes two parts; the loader registers `thelook_ecommerce.<table>` to match |
| `struct(1 AS a, 2 AS b).a` | `1` | `1` — identical |
| `SAFE_CAST` vs `try_cast` | `42` | `42` |
| `FARM_FINGERPRINT('x')` vs `xxhash64('x')` | `-4503883598042011646` | `-5636050478767222463` — **different algorithms**: why the harness hashes with `md5` on both instead |
| `date_diff(later, earlier, day)` vs `datediff(later, earlier)` | `14` | `14` (the BigQuery spelling raises on Spark, measured in phase 1) |
| `ORDER BY x NULLS LAST` | `1` | `1` — identical |

### Which models actually use which seam (measured: a scan of every `models/**/*.sql`)

Counted with `/home/hermes/.hermes/profiles/bruno/cache/scratch/macro_map.py` (every
`{{ macro(` call in the tree). The model tree contains **no** literal `qualify`, `unnest`,
`safe_cast`, `except_columns`, `generate_date_series`, `format_date_str`, `timestamp_trunc_to`,
`month_number`, `regexp_contains`, `element_at`, `pivot`, `string_agg` or `array_agg`: the
dialect seam is reached only through these macros.

| macro | calls | files |
|---|---|---|
| `int_type(` | 51 | 19 files (every staging model + most intermediate/marts) |
| `string_type(` | 34 | 8 files (the seven staging + dim_date) |
| `money_type(` | 25 | 14 files: 3 staging (order_items, products, inventory_items), 7 intermediate, 4 marts |
| `to_utc_timestamp(` | 12 | staging events, inventory_items, order_items, orders, users |
| `float_type(` | 4 | staging distribution_centers, users |
| `month_start(` | 4 | int_cohorts__user_months, int_users__first_order_cohort, dim_date, fct_orders |
| `safe_divide(` | 3 | int_products__returns, mart_cohort_retention, mart_product_performance |
| `generate_surrogate_key(` | 3 | int_cohorts__user_months, int_inventory__by_product_center, mart_cohort_retention |
| `seconds_between(` | 2 | int_events__sessions, int_inventory_items__enriched |
| `day_of_week_iso(` | 2 | dim_date |
| `date_diff_days(`, `explode_array_rows(`, `format_month(` | 1 each | dim_date |
| `ref(` / `source(` | 44 / 7 | dbt built-ins, not the seam |

The type macros and the `*_at` handling are what make 28 of the 29 models portable unchanged:
the seam is a **rename**, except for `dim_date.sql` (the `unnest` → `explode_array_rows` rewrite)
and the `money_type` scale decision. `decimal_type(` appears in the yml `data_type:`
declarations, not in model SQL; a precise count of that is the docs phase's job.