# SPEC — the BigQuery + Spark project (`bigquery_spark/`)

This is the design contract for the new two-engine project. It is written by the
orchestrator (Bruno) and is authoritative. **Implement what it says; if something in it is
wrong or impossible, stop and say so in `NOTES.md` rather than silently doing something else.**

Do not commit. Do not touch `main`. Do not edit the ROOT project's files (`../profiles.yml`,
`../dbt_project.yml`, `../Makefile`, `../macros/`, `../models/`, `../scripts/`) — the root
project is BigQuery + DuckDB and stays exactly as it is. Everything you write lives under
`bigquery_spark/`.

---

## 0. Measured environment facts (do not re-derive these; they were measured on this box)

* dbt is **dbt-oss 2.0.5** (dbt v2 / Fusion engine) at `../.venv/bin/dbt` (relative to this
  project). `DBT_PROFILES_DIR` must point at this project's root for every dbt call.
* **The `spark` adapter is experimental in dbt-oss 2.0.5 and is refused unless
  `DBT_ALLOW_EXPERIMENTAL_ADAPTERS=true` is exported.** Measured: without it, every command
  fails with `InvalidConfig (dbt1005): The 'spark' adapter is not yet supported by dbt.
  Supported adapters: snowflake, bigquery, databricks, redshift, duckdb, salesforce,
  clickhouse.` With it, the adapter loads. Every script that calls dbt must export it.
* **The spark adapter has NO `session` method.** Measured: `method: session` →
  `unknown variant 'session', expected one of 'thrift', 'http', 'livy', 'spark-connect'`.
  There is no in-process PySpark mode; a live Spark endpoint is required.
* **A real local Spark endpoint is available and works.** Spark 4.2.0 (pip `pyspark==4.2.0`)
  on JDK 21 (Temurin, both installed under `~/.local/spark`), started as a **Spark Thrift
  Server** (HiveServer2) on `127.0.0.1:10000` by `scripts/start_spark.sh`. `dbt debug` against
  it: **connection test OK**. Session facts read back through dbt:
  `current_catalog()=spark_catalog`, `current_database()=default`, `current_user()=hermes`,
  `current_timezone()=UTC`, `version()=4.2.0`.
* The profile needs `user:` — measured: `'user' is required when auth is 'PLAIN' or 'NONE'`.
* **The adapter cannot fetch ARRAY columns.** Measured: `dbt show --inline "select sequence(1,9,3) as s"`
  fails with `NotImplemented: [spark] Unsupported type ARRAY_TYPE`. Any query whose result set
  contains an array column fails at fetch time. Models whose final projection has no array are
  unaffected.
* BigQuery credentials exist at `~/.config/gcp/coreychimpbot-sa.json` (mode 600, outside the
  repo) and are passed via `BQ_KEYFILE`. **Never fake a BigQuery run.**

### Measured Spark SQL behaviour (through dbt against the real endpoint, 2026-10-06)

| construct | result |
|---|---|
| `select * except (b) from (...)` | **works** (Spark 4.2 supports the BigQuery spelling) |
| `select * exclude (b) from (...)` | parse error (DuckDB spelling, as expected) |
| `select date_day from unnest(...) as date_day` | **fails**: `UNRESOLVABLE_TABLE_VALUED_FUNCTION: Could not resolve unnest to a table-valued function` |
| `select explode(arr) as x from (...)` (subquery) | works |
| `... lateral view explode(arr) v as x` | works |
| `struct(1 as a, 2 as b)` + `s.a` | works (identical to BigQuery) |
| `date_trunc('week', ts)` | **Monday** (`2024-03-15 13:45:12` → `2024-03-11T00:00:00Z`); `'quarter'` → `2024-01-01`, `'month'` → `2024-03-01` |
| `timestamp_trunc(...)` | no such function (BigQuery-only) |
| `(dayofweek(d) + 5) % 7 + 1` | Friday → 5, Sunday → 7, Monday → 1 (the BigQuery shift, works unchanged) |
| `date_format(d, 'yyyy/MM/dd')` | works; **Java patterns, not strftime** (`'%Y/%m/%d'` is ambiguous and raises `INCONSISTENT_BEHAVIOR_CROSS_VERSION`) |
| `unix_micros(end) - unix_micros(start)` | `90.5` (microsecond precision) |
| `unix_timestamp(end) - unix_timestamp(start)` | `90.0` — **loses sub-second precision** |
| `try_cast('nope' as bigint)` | NULL (works) |
| `try_divide(1.0, 0.0)` | NULL; `try_divide(1.0, 4.0)` → 0.25 |
| `regexp_like(x, p)` and `x rlike p` | both work |
| `md5(concat_ws('||', '1', 'x'))` | `df6729622b8fb993f31b1ba95a27e5cc` — **identical to the DuckDB self-check's expected value** |
| `cast(1 as decimal(39,2))` | **fails**: `DECIMAL_PRECISION_EXCEEDS_MAX_PRECISION: Decimal precision 39 exceeds max precision 38` |
| `typeof(...)` | `bigint`, `string`, `double`, `timestamp`, `decimal(18,2)`, `decimal(38,9)`, `array<bigint>` |
| `cast(timestamp'...' as string)` | `2024-03-15T13:45:00Z` (instant, rendered UTC); `timestamp_ntz` renders naive |

---

## 1. Why `bigquery_spark/` and not `examples/spark/`

Write this reasoning into the project README.

* It is a **second, independent project**, not an example or a generated variant. The root
  project is `bigquery-duckdb-dbt-experiments`; its `examples/duckdb_only/` is a *worked
  example* of moving three models by hand, not a peer project. A peer belongs beside it.
* The folder name names its two engines, exactly as the root project's name does, so a reader
  knows the scope without opening anything: **BigQuery + Spark, two targets, no third engine.**
* Its own `dbt_project.yml` and `profiles.yml` keep the root project's guardrail intact (the
  root project's files are not edited) and keep the root project's portability scan, which
  walks `models/` and `analyses/`, unaware of this tree.
* **No DuckDB anything.** No DuckDB token list, no DuckDB fixture, no DuckDB profile entry.
  If DuckDB appears in this project it is a bug.

---

## 2. Layout

```
bigquery_spark/
  README.md                     what is verified, what is not, with real command output
  dbt_project.yml               name/profile: bq_spark_experiments
  profiles.yml                  two outputs: spark (local thrift) and bigquery
  packages.yml                  empty, same discipline as the root project
  models/                       copied as-is from ../models, then diverged only where Spark forces it
  macros/polyglot/              two-engine seam, house style: default__ = Spark, bigquery__ = BigQuery
  tests/                        copied as-is from ../tests
  analyses/polyglot_showcase.sql
  scripts/
    install_prereqs.sh          JDK 21 + pyspark + start the local endpoint
    start_spark.sh / stop_spark.sh
    check_env.sh                prerequisites for both targets
    load_spark_sources.py       real BigQuery rows -> local Parquet -> Spark tables
    check_portability.py        two-target guardrail
    parity.py                   Spark vs BigQuery, per column
    spark_check.sh              the whole Spark side in one command
    pre_pr.sh                   check-env + guardrail + parity
  docs/
    bigquery-to-spark.md        THE INCOMPATIBILITY CATALOGUE (the deliverable)
    conclusion.md               the decision-maker conclusion
  Makefile
```

`default__` = **Spark**; `bigquery__` = **BigQuery**. The dispatch namespace is
`bq_spark_experiments` on every `adapter.dispatch(...)` call.

---

## 3. The models: copy, then diverge only where Spark forces it

Copy `../models/`, `../tests/` and `../analyses/polyglot_showcase.sql` **verbatim** as the
starting point. Then change only what will not render or run on Spark. Every change must be
justified in `docs/bigquery-to-spark.md`. Do not refactor, rename, or "improve" anything else.

Known divergences to make (all measured, section 0):

1. **`dim_date.sql` — `unnest` in FROM.** `cross join unnest(<array>) as <alias>` is
   BigQuery-only; Spark has no `unnest` table-valued function. Replace the `unnest_alias`
   macro with a **FROM-clause fragment macro**:
   ```
   explode_array_rows(array_expr, alias)
     default__ (spark):  lateral view explode(<array_expr>) <alias>__arr as <alias>
     bigquery__:         cross join unnest(<array_expr>) as <alias>
   ```
   and the model becomes
   ```
   from bounds
   {{ explode_array_rows(generate_date_series('first_date', 'last_date'), 'date_day') }}
   ```
   This is the one place the root project's recorded rule ("`unnest` is deliberately NOT a
   macro") breaks, and it must be written up as such.

2. **`except_columns`** — Spark 4.2 accepts `* except (a, b)`, so **both branches render the
   BigQuery spelling**. Keep the macro (the seam should have one shape) and say in its
   docstring that the two engines now agree, so the macro exists for symmetry, not divergence.

3. **`generate_series` / `generate_date_series`** — Spark's `sequence(start, stop[, step])`
   is the generator; for dates `sequence(start, stop, interval n part)` returns `ARRAY<DATE>`
   exactly as BigQuery's `generate_date_array` does.

4. **`timestamp_trunc_to`** — Spark's `date_trunc('<part>', <expr>)` (quoted string, like
   DuckDB); keep the `week(monday)` behaviour on the BigQuery branch and plain `week` on Spark
   (measured: Spark's `week` is already Monday).

5. **`format_date_str` / `format_month`** — Spark's `date_format` takes a **Java** pattern.
   The macro's `fmt` argument stays strftime-style (the project's canonical), and the Spark
   branch translates `%Y %m %d %j %a %b %H %M %S` to `yyyy MM dd DDD EEE MMM HH mm ss`.
   Anything else is a compiler error. This is a genuine incompatibility: the *format-string
   language* differs, not just the function name.

6. **`safe_cast`** → `try_cast`; **`safe_divide`** → `try_divide(cast(n as double), cast(d as double))`.

7. **`date_diff_days`** → Spark `datediff(<later>, <earlier>)` (days, later − earlier).

8. **`seconds_between`** → `cast(unix_micros(<end>) - unix_micros(<start>) as double) / 1000000.0`.
   Do **not** use `unix_timestamp`: measured to drop the microseconds.

9. **`regexp_contains`** → Spark `regexp_like(<expr>, <pattern>)`.

10. **`day_of_week_iso`** → the BigQuery arithmetic form (`(dayofweek(x) + 5) % 7 + 1`),
    measured identical.

11. **`money_type()`** → Spark `decimal(18,2)`; BigQuery `numeric`. **This is the money
    prediction: Spark DECIMAL is exact to its declared scale, like DuckDB's, so the same class
    of money difference against BigQuery NUMERIC(38,9) is expected. It must be measured, not
    assumed** (see section 6).

12. **`decimal_type(p, s)` — the decimal guard.** Spark's `DECIMAL(p,s)` caps at **p = 38**
    (measured: `DECIMAL_PRECISION_EXCEEDS_MAX_PRECISION: Decimal precision 39 exceeds max
    precision 38`), while BigQuery reaches `BIGNUMERIC` at 76.76 digits. So:
    * `p <= 38` → Spark `decimal(p,s)`; BigQuery `numeric` when `s <= 9` else `bignumeric`.
    * `p > 38` → BigQuery `bignumeric`; Spark **`raise_compiler_error`** naming Spark's
      ceiling, the BigQuery ceiling, and the two legal ways out (declare a narrower decimal,
      or `float_type()` and accept 15–16 significant digits). **Never silently render
      `double`.** The error message must state the limit per engine, not assume.

13. **`struct_literal`** → Spark `struct(1 as a, 2 as b)`: identical to BigQuery. Both branches
    render the same thing; say so in the docstring.

14. **`month_number`, `to_string`, `to_utc_timestamp`, `int_type`, `string_type`,
    `float_type`, `timestamp_type`, `type_bigint_array`, `generate_surrogate_key`** — work out
    each from the measurements in section 0 and record the outcome either way.
    * `timestamp_type()` → `timestamp` on both. **The timezone decision**: the Spark session
      runs with `spark.sql.session.timeZone=UTC` (measured `current_timezone()=UTC`) so a
      Spark `TIMESTAMP` is an instant rendered in UTC, which is what BigQuery's `TIMESTAMP`
      is. `to_utc_timestamp(expr)` on Spark is therefore `cast(<expr> as timestamp)`. **Prove
      the session time zone in a self-check** (`current_timezone()`), and measure and record
      what a **non-UTC** session would do — that is the open timezone gotcha the root project
      carried, and it must be reported, not hidden.
    * `type_bigint_array()` → Spark `array<bigint>`; BigQuery `array<int64>`.
    * `string_type()` → Spark `string` (Spark has no VARCHAR); identical to BigQuery.
    * `int_type()` → `bigint`; `float_type()` → `double`.

15. **`self_check.sql`** — `polyglot_render` and `polyglot_selfcheck`. Unlike the root project,
    **the Spark target can be executed**, so `polyglot_selfcheck` must run on **both** targets
    (Spark and, when a credential is present, BigQuery). Reuse the root project's case list
    (read `../macros/polyglot/self_check.sql`) and add: the decimal ceiling on Spark, the
    session time zone, `seconds_between` microsecond precision, `except_columns`, and the
    surrogate-key value. Where a case cannot be written for one engine, skip it *by name* and
    say so — never silently drop a case.

Everything else in `models/` must be **unchanged**. Count how many model files needed no
change at all and put that number in the catalogue and the conclusion.

---

## 4. The two-target portability gate (`scripts/check_portability.py`)

Model it on `../scripts/check_portability.py` (read it first; keep its structure, its
comment-stripping, its `--demo`, its exit codes 0/1/2 and its printed counts). Differences:

* Targets are `("bigquery", "spark")`.
* Compile into `target/portability/<target>/`.
* Two directional token lists, **each token measured against the real engines on this box
  before it goes in the list**. Seed candidates:
  * must NOT appear in the Spark render: `float64`, `safe_cast`, `safe_divide`,
    `generate_array`, `generate_date_array`, `regexp_contains`, `format_date(`, `timestamp_trunc`,
    `timestamp_diff`, `bignumeric`, `array<int64>`, `bigquery-public-data`, and
    `date_diff(` not followed by a quote.
  * must NOT appear in the BigQuery render: `try_cast`, `try_divide`, `sequence(`, `explode(`,
    `lateral view`, `date_format(`, `datediff(`, `dayofweek(`, `unix_micros(`, `regexp_like(`,
    `timestamp_ntz`, `array<bigint>`, `spark_catalog`, `default.thelook_ecommerce`.
  * **`* except (` is deliberately NOT in either list** — measured to work on both engines.
    Say so in a comment.
* Purity check unchanged: nothing under `models/` or `tests/` may mention `target.type`,
  `target.name`, `target.database`, `target.schema` or `adapter.type`. One allowlist entry,
  with its reason: `models/staging/_thelook__sources.yml` (the source *database* is the one
  genuinely target-dependent thing).
* `--demo` must still prove the guardrail can fail and then pass.
* Print the counts: `compiled files checked: N (models: M, analyses: K)`,
  `BigQuery-only tokens in the Spark render: 0/X`, `Spark-only tokens in the BigQuery render: 0/Y`,
  `target-branch findings: 0`, and `PORTABLE` / `NOT PORTABLE: n finding(s)`.

---

## 5. Getting the same rows into Spark (`scripts/load_spark_sources.py`)

The Spark target must read **the same real rows** as the BigQuery target, exactly as the root
project's `make value-parity` loads the real rows into DuckDB before comparing. There is **no
DuckDB here** — do not use the DuckDB CLI, the DuckDB extension, or `dev.duckdb` for anything.

* Pull the seven real tables from `bigquery-public-data.thelook_ecommerce` with the
  **BigQuery Python client** (`google-cloud-bigquery` + `pyarrow`, installed by
  `scripts/install_prereqs.sh`), using a **table read, not a query job**, so no bytes are
  billed (the root project's loader makes the same distinction).
* Write one Parquet directory per table under `target/spark_sources/<table>/`, then register
  each as a table in the Spark catalog the models read: `thelook_ecommerce.<table>`.
  (`CREATE DATABASE IF NOT EXISTS thelook_ecommerce; CREATE OR REPLACE TABLE ...`)
* Report per table: rows written, and BigQuery's `numRows` from table metadata; **fail** on a
  mismatch. Everything printed also goes to a log file.
* Timestamps: the source contract is an absolute instant. Parquet carries the instant; the
  Spark session is pinned to UTC. **Prove it** — report each timestamp column's min/max as an
  instant and state whether the load moved any instant.
* The heavy tables (`events` ≈ 2.43M rows, `inventory_items` ≈ 490k) are expected to take
  minutes; print progress per table. Support `--tables a,b,c` to load a subset while iterating.

---

## 6. Value parity (`scripts/parity.py`)

Model it on `../scripts/parity.py` (read it; keep the per-column pattern and the TRAPS
reasoning). Compare **Spark vs BigQuery**:

* per model: row count, column names, canonical column types, one order-independent
  per-column checksum, per-column null count and distinct count;
* `--same-data` gates row counts and checksums as well as names and types; **it is the default
  here**, because both legs read the same real rows by construction;
* exit 0 = parity established and every gate matched; 1 = a real mismatch; 2 = a leg could not
  be measured (say which, and why) — never a silent pass;
* write `parity-report.md` and `parity-report.json` in the project root.

Canonical-type and value rules to carry over: floats compared as `ROUND(x * 1000000)` integer
micro-units, never as text; timestamps compared as instants (Spark: `unix_micros(x)`; BigQuery:
`UNIX_MICROS(x)`); decimals compared by kind (`decimal == numeric`), never by precision, with
both raw type strings always in the report; arrays/structs compared structurally; nothing
depends on row order.

**The money prediction, which the report must answer explicitly.** The root project found that
DuckDB and BigQuery disagree on money because `decimal(18,2)` is exact to its declared scale
while BigQuery `numeric` keeps nine decimals. Spark's `DECIMAL(p,s)` is likewise exact to its
declared scale, so **the same class of money difference is predicted between Spark and
BigQuery**. Report whether it appears, and if it does not, explain why the reason matters more
than the result. A per-column breakdown naming every differing money column and the count of
differing rows is the evidence; "they differ" is not.

---

## 7. Required deliverable: `docs/bigquery-to-spark.md`

**This is what the client is buying.** One row per construct:

| Construct | BigQuery | Spark | Handled by | Notes / residual risk |
|---|---|---|---|---|

Rules:
* **Include the constructs that needed no change too**, with a count of how many model files
  were portable untouched. A list of only the problems misrepresents the difficulty.
* Name anything with no clean equivalent and what the workaround costs — a rewrite, a
  subquery, a behaviour change.
* **No "should work" rows.** Every row says what was measured, on which engine and version, or
  says **unverified** and why.
* Cover at least the constructs the card names: `SAFE_CAST`, `QUALIFY`, `SELECT * EXCEPT` /
  `* REPLACE`, `UNNEST` and alias handling, array indexing (`OFFSET`/`ORDINAL` zero-based vs
  `element_at` one-based), `GENERATE_DATE_ARRAY` / `GENERATE_ARRAY`, date and time
  (`PARSE_DATE` vs `to_date`, `FORMAT_DATE` vs `date_format`, `EXTRACT`, `DATE_TRUNC`),
  TIMESTAMP vs TIMESTAMP_NTZ, `STRING_AGG`, `APPROX_COUNT_DISTINCT`, `ARRAY_AGG` with
  `IGNORE NULLS` / `LIMIT`, `PIVOT`, recursive CTEs, numeric types and implicit casts, and
  two-part vs three-part identifiers. For each: say whether this project actually uses it
  (grep the model tree and say which model), and if it does not, say that plainly — a
  construct the project never uses is still a finding worth one line.

## 8. `docs/conclusion.md` — for a decision-maker

Plain English, no jargon, no diff. Three parts: how much of the project ported unchanged; what
the recurring costs are (what needs a branch, what needs a rewrite, what needs a new habit);
and what to warn them about. Name the decimal ceiling, the `unnest` rewrite, the
`DBT_ALLOW_EXPERIMENTAL_ADAPTERS` gate, the missing `session` method, and the timezone
decision. State the count of models that render and the count that executed, with the runtime
named.

---

## 9. Definition of done

1. `make spark` exits 0: the Spark endpoint is up, the sources are loaded, and
   `dbt build --target spark` builds every model with every test passing. Report the counts.
2. `dbt build --target bigquery` exits 0 (real BigQuery, credentials present).
3. `python3 scripts/check_portability.py` exits 0 with the counts printed, and
   `--demo` exits 0 having shown it fail and pass again.
4. `python3 scripts/parity.py` exits 0 (or 2 with the reason named) and its report is
   committed.
5. `dbt run-operation polyglot_selfcheck --target spark` exits 0 with every case `ok`;
   the decimal-ceiling case fails on Spark **by design** and the failure is captured.
6. `docs/bigquery-to-spark.md` and `docs/conclusion.md` exist and are committed.
7. `README.md` states what is verified and what is not, with real command output pasted in.
8. `NOTES.md` lists every model file changed and why, and every construct that needed no
   change.
9. **`git -C .. status --short` shows the root project's files untouched.**