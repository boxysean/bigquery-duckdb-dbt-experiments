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

## 6. Workspace hygiene

The root project is untouched: only `bigquery_spark/` was added, and `git -C .. status` shows
no modification to the root project's tracked files.