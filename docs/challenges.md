# Challenges hit while building this project, in the order they were hit

**All 29 models are one source file each that renders for both targets, with no fork and no
`target.type` branch, and today both targets build all 29 (196/196 on DuckDB; 195/196 plus
one intentional warning on BigQuery).** The remaining difference costs about 5.1 macro call
sites per model. On the same input rows the targets do *not* produce the same values: row
counts agree on all 29 models, but every value agrees on 8 of 29 and on 1 of the 11 marts,
because money is rounded to cents on one engine only ("The verdict", 9.1).

Each entry has four parts: symptom (real text, with its `source:`), cause, resolution, and
classification: **dual-target** (inherent to dual-target dbt), **DuckDB 1.5.5 / ext 27d85ad**
(this DuckDB version or the community extension build), **environment** (permissions,
credentials, the box) or **dbt v2** (dbt-oss 2.0.5). See also [`gaps.md`](gaps.md) and
[`move_to_duckdb.md`](move_to_duckdb.md). The table at the end maps every claim to evidence.

## 1. Scaffold and prerequisites (t_f8a5c635)

### 1.1 The DuckDB `bigquery` extension has no core build

* **Symptom.**
  ```
  HTTP Error: Failed to download extension "bigquery" at URL "http://extensions.duckdb.org/v1.5.5/linux_amd64/bigquery.duckdb_extension.gz" (HTTP 404)
  ```
  source: `analyses/transport_a/logs/t01.log:21`. First recorded by the scaffold ("A bare
  name is only looked up in the CORE repository", `README.md:810-813`); t01 re-measured it
  with an empty `HOME`.
* **Cause.** `bigquery` is a community extension; `INSTALL bigquery` searches core only.
* **Resolution.** `INSTALL bigquery FROM community` works (t02: build `27d85ad`,
  `installed_from = community`). `scripts/install_prereqs.sh` runs it once, and
  `scripts/check_env.sh` fails loudly when it is missing.
* **Classification.** DuckDB 1.5.5 / ext 27d85ad: published in the community repo only.

### 1.2 `profiles.yml` cannot express a community extension

* **Symptom.**
  ```
  InvalidConfig (dbt1005): Configuration Error: extensions: item 2 must be a string, got Mapping {name, repo}
  Failed to download extension "bigquerycommunity"
  ```
  source: `README.md:795-809`, `profiles.yml:21-31`. The first is `{name: bigquery, repo:
  community}`, the second `"bigquery:community"`; a bare `bigquery` 404s against core (1.1).
* **Cause.** dbt-oss 2.0.5's profile schema accepts only plain strings under `extensions:`
  (the name/repo form appears to follow the Python `dbt-duckdb` adapter's docs).
* **Resolution.** Workaround: install out of band; the plain name then loads the cached
  community build (`profiles.yml:32-41`).
* **Classification.** dbt v2: the profile schema has no field for an extension's repository.

### 1.3 The bundled DuckDB driver: the brief was wrong

* **Symptom.** The brief repeated that dbt v2's bundled driver "cannot load extensions". It
  did not reproduce: with the dbc driver hidden, the bundled driver ran the `INSTALL`s and
  loaded `httpfs` and `iceberg`. What it changed was the engine: DuckDB **1.5.4** instead of
  the pinned 1.5.5, silently. source: `README.md:814-820`, `scripts/check_env.sh:62-63`.
* **Cause.** The bundled driver carries its own DuckDB build.
* **Resolution.** `dbc install duckdb` is a hard prerequisite; `check_env.sh` fails without
  it (`scripts/check_env.sh:65,81`).
* **Classification.** dbt v2: which engine dbt runs, not an extension limitation.

## 2. The model tree and the DuckDB fixture (t_d0cac5da)

### 2.1 dbt v2 API traps that cost time

* **Symptom.**
  ```
  DbtYamlValidationError dbt1159
  [warning] [UnusedResourceConfigPath (dbt1097)]: Configuration paths exist in your dbt_project.yml file which do not apply to any resources.
  Parser Error: syntax error at or near "limit"
  ```
  source: `SPEC.md:33-34`, `NOTES.md:207`, `NOTES.md:810-811`. Also: `dbt ls --resource-type
  model --target duckdb | wc -l` printed `36` for 28 models (`NOTES.md:734-738`); a junk key
  in the bigquery output passes `dbt parse` (`README.md:821-824`); `dbt clean` "resolves the
  duckdb profile first, which opens the very file it is asked to delete" (`Makefile:134-136`).
* **Cause.** Generic test arguments must sit under `arguments:`. The skeleton configured
  `intermediate`/`marts` before they had models. `dbt show --inline` appends its own
  `limit`. `dbt ls` prints its banner to stdout. `dbt parse` only renders the profile.
  `dbt clean` opens the DuckDB connection first.
* **Resolution.** Nested `arguments:` everywhere; the warning went once each layer had
  models (`NOTES.md:663`); `dbt show --limit N`; `dbt ls --quiet` (→ `28`); `dbt debug` for
  profile fields; `make clean` uses `rm -rf`, not `dbt clean`.
* **Classification.** dbt v2.

## 3. The macro layer and the portability guardrail (t_44abf1ef)

### 3.1 The decimal ceiling: BIGNUMERIC has no DuckDB equivalent

* **Symptom.**
  ```
  Binder Error: DECIMAL type width must be between 1 and 38
  ```
  source: `README.md:213-215`; reproduced in this worktree on 2026-09-27 by
  `duckdb -c "select cast(1 as decimal(77,38))"` (v1.5.5), exit 1, exactly that line.
* **Cause.** DuckDB's DECIMAL stops at 38 digits; BigQuery's BIGNUMERIC has 76.76.
* **Resolution.** `decimal_type(p > 38)` renders `bignumeric` on BigQuery and raises a
  compiler error on DuckDB (`Refusing to fall back to DOUBLE silently.`,
  `README.md:226-229`), never a silent `double`.
* **Classification.** dual-target: a type-system gap, not a setting (it bites again in 7.3).

### 3.2 The date spine: `unnest`'s alias in `FROM`, and the series' element type

* **Symptom.** On DuckDB the BigQuery alias spelling binds to the **table**, and the date
  series is not a date array:
  ```
  select typeof(date_day) from (select 1 as x) t cross join unnest(cast(generate_series(
    date '2024-01-01', date '2024-01-03', interval 1 day) as date[])) as date_day
  → STRUCT(unnest DATE)           (… as date_day__unnest(date_day) → DATE)
  select typeof(generate_series(date '2024-01-01', date '2024-01-03', interval 1 day))
  → TIMESTAMP[]
  ```
  source: reproduced with `duckdb -c` (v1.5.5) in this worktree, 2026-09-27; recorded at
  `macros/polyglot/arrays.sql:10-18,50-54` and `NOTES.md:1009-1014`.
* **Cause.** BigQuery binds `unnest(arr) as x` to the element, DuckDB to the relation, and
  BigQuery rejects DuckDB's column-alias form. BigQuery's `GENERATE_DATE_ARRAY` returns
  `ARRAY<DATE>`; DuckDB's date `generate_series` needs an explicit interval and returns
  timestamps.
* **Resolution.** A new dispatched **helper**, `unnest_alias` (`models/marts/dim_date.sql:18`)
  — the only place the seam grew a helper rather than a branch (`README.md:303-307`) — and
  a `date[]` cast in `generate_date_series`'s DuckDB branch.
* **Classification.** dual-target: the alias difference is relation-level, so no expression
  macro can hide it.

### 3.3 Month steps drift from a month-end start on DuckDB

* **Symptom.**
  ```
  duckdb -c "select unnest(cast(generate_series(date '2024-01-31', date '2024-06-30', interval 1 month) as date[])) as d"
  2024-01-31, 2024-02-29, 2024-03-29, 2024-04-29, 2024-05-29, 2024-06-29
  ```
  source: reproduced in this worktree, 2026-09-27 (v1.5.5); `macros/polyglot/arrays.sql:57-60`.
* **Cause.** DuckDB adds the interval to the *previous* element, so once February clips the
  31st to the 29th, every later month stays on the 29th.
* **Resolution.** Not solved; the caveat is documented in `macros/polyglot/arrays.sql`
  (start month steps on the 1st). BigQuery's behaviour here is unmeasured ([`gaps.md`](gaps.md)).
* **Classification.** DuckDB 1.5.5 (measured there); possibly dual-target (BigQuery unknown).

### 3.4 Normalisation traps in the date/time macros

* **Symptom.** Three SPEC renderings were wrong: `format_date(expr, fmt)` for
  `format_date(fmt, expr)`, `%` for `mod(...)`, bare `week` for `week(monday)`.
  source: `NOTES.md:1016-1023`, `macros/polyglot/dates.sql:31,70,92-94`.
* **Cause.** `FORMAT_DATE` takes the format first, `STRFTIME` the value first. BigQuery's
  bare `WEEK` starts on Sunday; DuckDB's `'week'` is ISO. BigQuery's `DAYOFWEEK` numbers
  Sunday 1 and it has no `%` operator. A wrong formula still runs on DuckDB.
* **Resolution.** All three corrected during implementation; `day_of_week_iso` renders
  `(mod(extract(dayofweek from …) + 5, 7) + 1)`.
* **Classification.** dual-target.

## 4. The parity harness (t_52340fa8; defect follow-up t_c5b39ecf)

### 4.1 `SAFE_DIVIDE` returns its inputs' type

* **Symptom.** `mart_product_performance.gross_margin_rate` was `DOUBLE` on DuckDB and
  `NUMERIC` on BigQuery, the gating mismatch that made `make parity` exit 1
  (`parity: MISMATCH. gating: ['mart_product_performance']`). source: `NOTES.md:1186-1196,1218`.
* **Cause.** `bigquery__safe_divide` applied `SAFE_DIVIDE` to the columns' own NUMERIC type,
  which it returns; the DuckDB branch cast both sides to double.
* **Resolution.** Commit `cbe259c`: the BigQuery branch casts both sides to `float_type()`
  (`macros/polyglot/math.sql:23-24`). Deliberate exception: the two `average_order_value`
  money metrics keep `round(x / nullif(y, 0), 2)` as `money_type()` (`README.md:308-316`).
* **Classification.** dual-target: one name, two typing rules; only a two-target harness saw it.

## 5. The BigQuery leg's tests against the real dataset (t_d87cf14b)

### 5.1 Three real tests failed, and a fourth was hidden by dbt's skipping

* **Symptom.** The first `make bq` exited 1: `not_null_stg_thelook__events_user_id` (1,124,610
  rows), `accepted_values` on `events.traffic_source` (2 distinct values) and
  `assert_timestamps_are_before_after` (137,795 rows). source: `NOTES.md:827-839`.
* **Cause.** The fixture encoded three false assumptions: every event has a user, events
  share the users' traffic-source vocabulary, and `order_items.created_at` follows its
  order. The harness printed only the first lines of dbt's failure block, and dbt skipped
  122 nodes downstream, so the fourth failure (5.2) surfaced only after these were cleared.
* **Resolution.** A `relationships` test on non-null ids replaced `not_null`; the accepted
  list and the fixture now carry the measured vocabulary; the `created_at` pairs became a
  `severity: warn` test (`NOTES.md:849-878`) — today's one `make bq` warning.
* **Classification.** dual-target: a fixture encodes assumptions; the real leg tests them.

### 5.2 `accepted_values` on a boolean column is a portability trap

* **Symptom.**
  ```
  Error 400: No matching signature for operator IN for argument types BOOL and {STRING}
  ```
  source: `NOTES.md:840`, for `accepted_values_dim_date_is_weekend__True__False`.
* **Cause.** dbt renders the literals quoted (`BOOL not in ('True','False')`); DuckDB
  coerces, BigQuery refuses.
* **Resolution.** Removed (`not_null` covers a computed boolean); the trap is in the column
  description so nobody re-adds it (`models/marts/_marts__models.yml:350-356`).
* **Classification.** dual-target, and dbt v2 (the quoting is dbt's).

## 6. Transport A: the community extension (t_d4637e87)

### 6.1 Two reproducible bugs in the extension

* **Symptom.**
  ```
  Invalid Input Error: Failed to cast value: Unimplemented type for cast (GEOMETRY('OGC:CRS84') -> BIGINT[])
  INTERNAL Error: Attempted to access index 2 within vector of size 2
  ```
  source: `analyses/transport_a/logs/t17.log:49`, `analyses/transport_a/logs/t18.log:29`.
* **Cause.** On `use_rest_api := true`, a projection naming a column twice mis-maps later
  columns' types; projecting named columns out of a `dry_run := true` result trips an
  internal assertion and kills the process.
* **Resolution.** Workarounds: the Storage path; `SELECT *` on dry-run rows
  (`analyses/transport_a/README.md:287-306`).
* **Classification.** DuckDB 1.5.5 / ext 27d85ad.

### 6.2 Writes through the extension are the weak leg

* **Symptom.**
  ```
  Failed to create write stream: NOT_FOUND ... Cannot create BigQuery write stream to
  projects/coreychimpbot/datasets/experiments_dev/tables/transport_a_probe
  ```
  source: `analyses/transport_a/README.md:237-241` (the log keeps only the scenario comment,
  `t12b.log:12-16`), for a table created moments earlier in the same session. In a fresh
  session the insert took 5.6 s (run of record), 11.3 s and 128.7 s (82 `Retrying...` lines).
* **Cause.** Not permissions: DDL and write both landed. The Storage Write API does not see a
  same-session table; why the timing swings is not established.
* **Resolution.** Not solved; the caveat is documented in `analyses/transport_a/README.md`
  (insert from a second session; read with the extension, do not write).
* **Classification.** ext 27d85ad.

### 6.3 `INFORMATION_SCHEMA.JOBS_BY_PROJECT` is not readable

* **Symptom.** `Permission Error: BigQuery Permission Denied` on it.
  source: `analyses/transport_a/README.md:308-312`.
* **Cause.** It needs a resource/metadata-viewer role the account lacks.
* **Resolution.** `bigquery_jobs('coreychimpbot')`, which exposes `bytes_processed`, not
  `bytes_billed`; billing is computed as `max(10 MiB, bytes_processed)`.
* **Classification.** environment.

## 7. Transport B: `EXPORT DATA` to GCS (t_69095c72)

### 7.1 Two refusals in the export path

* **Symptom.**
  ```
  Only simple types may be exported as CSV but variable has type ARRAY<INT64>
  Error while reading data, error message: Type JSON is not currently supported for parquet exports.
  ```
  source: `analyses/transport_b/logs/b14.log:64`, `b13c.log:63`.
* **Cause.** CSV cannot carry nested/repeated types. JSON→Parquet is refused, a limit the
  export-limitations page does not list; JSON→CSV works (b14b, the control).
* **Resolution.** Nested data as Parquet; JSON as CSV (or cast to STRING).
* **Classification.** dual-target: BigQuery's export rules, inherited by any file hand-off.

### 7.2 An unordered export's row order is not reproducible

* **Symptom.** Three identical exports gave the same two chunks, but run B's file 0 is
  byte-for-byte run A's file 1 (`238054 rows · d28275cb555862308a6570acc846d1f5`) and vice
  versa; `temp` decreases 118,548 times in A's file 0. source:
  `analyses/transport_b/logs/b24.log:51-66`.
* **Cause.** One shard per parallel worker, with nothing fixing which worker writes which file.
* **Resolution.** `ORDER BY` makes the artifact reproducible (1 file, 0 descents, 4,038,747
  rows), at the cost of parallelism (1 file instead of 17).
* **Classification.** dual-target (BigQuery export semantics, as 7.1).

### 7.3 BIGNUMERIC is dropped silently

* **Symptom.** In Parquet it becomes a `double`, `1.234567890123457e+37`: 16 significant
  digits of 38, no error or warning (`analyses/transport_b/README.md:150,153-157`, b18b).
  Through the extension it arrives as `VARCHAR`, even with `bq_bignumeric_as_varchar =
  false` (`analyses/transport_a/README.md:173,193-196`).
* **Cause.** DuckDB's DECIMAL width (3.1); the export narrows to float, the extension to text.
* **Resolution.** Not solved; the caveat is documented in `analyses/transport_b/README.md`
  (read it directly or cast it in the export). No model has a BIGNUMERIC column.
* **Classification.** dual-target.

## 8. The two-repo fallback and the guardrail's scope (t_ef8e0090, t_75db4537)

### 8.1 The guardrail scanned the transport scenarios and stayed red

* **Symptom.** `compiled files checked: 90 (models: 29, analyses: 61)`,
  `NOT PORTABLE: 39 finding(s)`: 12 in `analyses/transport_a/sql/`, 27 in
  `analyses/transport_b/sql/`, 0 in `models/`. source: `docs/move_to_duckdb.md:586-591` (the
  before-state, left there on purpose).
* **Cause.** dbt-oss 2.0.5 parses every `.sql` under `analyses/` as an analysis (today:
  `Processed: 29 models | 167 tests | 61 analyses`), so the engine-specific scenarios were
  compiled and scanned.
* **Resolution.** Commit `60b0c5d`: `EXCLUDED_ANALYSES = ("analyses/transport_a",
  "analyses/transport_b")` (`scripts/check_portability.py:40`), and the check prints what it
  dropped — in this worktree on 2026-09-27, `analyses/transport_a  22 file(s)`,
  `analyses/transport_b  38 file(s)`, then `PORTABLE`.
* **Classification.** dbt v2 (all of `analyses/` is parsed), and dual-target (a guardrail
  must know which files are warehouse code).

### 8.2 A `MacroSyntaxInvalid` warning: recorded, not reproduced

* **Symptom.** Recorded once, while `docs/move_to_duckdb.md` lived at
  `analyses/move_to_duckdb/README.md`:
  ```
  [warning] [MacroSyntaxInvalid (dbt1502)]: Failed to parse macro SQL syntax error: unexpected character (in analyses/move_to_duckdb/README.md:235:54)
  ```
  source: the orchestrator's record for this card — the text is in no file in this repo.
  `.cc-move-run3.json` (committed) records the move to `docs/`, after which both
  `dbt parse` runs "printed no `MacroSyntaxInvalid` line".
* **Cause.** Unknown. On 2026-09-27 the orchestrator probed with a `.md` under `analyses/`
  containing `{{ config(...) }}` and `{% set x = ... %}`, through `dbt parse` and
  `dbt compile`. **It did not warn.**
* **Resolution.** Recorded and not reproduced; the document lives under `docs/`, which dbt
  does not parse.
* **Classification.** dbt v2, if real.

## 9. Value parity on one real dataset (t_d92586d6)

### 9.1 One decimal value, two texts: the checksum hashed the rendering

* **Symptom.** Columns such as `stg_thelook__order_items.sale_price` had equal distinct counts
  on both legs and different checksums. The probe shows why the text differs:
  ```
  constants:
    duckdb   [{'a': '12.30', 'b': '12.00', 'c': '0.50'}]
    bigquery [{'a': '12.3', 'b': '12', 'c': '0.5'}]
  ```
  source: `analyses/value_parity/logs/probe_decimal_text.log:3-5`. The digest self-check had
  passed throughout, because its decimal constants (`12.34`, `-0.05`) have no trailing zero.
  How many differences the rendering alone caused before the fix is not in a log.
* **Cause.** `CAST(<decimal> AS text)` keeps the declared scale on DuckDB (`DECIMAL(18,2)`)
  and is shortest-form on BigQuery (`NUMERIC`), and the harness hashed that text. TRAP 2
  compared decimal *types* by kind but never their *text*.
* **Resolution.** `scripts/parity.py:281-291` (`Engine.canon`, kind `decimal`) strips
  trailing fractional zeros on both engines; the self-check gained `12.30` and `12.00` rows
  on both sides (`scripts/parity.py:612-613,629-630`), so the rule is proved on every run.
  After the fix the money columns still differ: BigQuery keeps sub-cent digits
  (`0.49000001`, `1.50999999`, `probe_decimal_text.log:8`), a value difference, not a
  rendering one ([`gaps.md`](gaps.md) §1).
* **Classification.** dual-target: the two engines print the same decimal differently.

### 9.2 The extension's zone-less `TIMESTAMP` breaks the source contract

* **Symptom.** Loaded as the extension returns them, every `*_at` value moves when
  `to_utc_timestamp` reads it (session `Europe/Vienna`):
  ```
  table                  column         type                        non_null   shifted  shift_h      min_value                        macro_of_min
  events                 created_at     TIMESTAMP                    2425698   2425698  [-2.0, -1.0] 2019-01-02 00:20:00              2019-01-01 23:20:00
  orders                 created_at     TIMESTAMP                     124952    124952  [-2.0, -1.0] 2019-01-15 07:03:47              2019-01-15 06:03:47
  ```
  source: `analyses/value_parity/logs/loader-raw-timestamps.log:121-122,129`. All 12
  timestamp columns are shifted on 100% of their non-null rows (`:122-133`).
* **Cause.** The extension returns a BigQuery `TIMESTAMP` as a zone-less DuckDB
  `TIMESTAMP` (`analyses/transport_a/README.md:179`). The source definition declares
  `TIMESTAMPTZ` on DuckDB (`models/staging/_thelook__sources.yml:16`), and
  `default__to_utc_timestamp` casts through `timestamptz`
  (`macros/polyglot/casting.sql:49-51`), so a naive value is read in the session time zone.
* **Resolution.** The loader delivers every `TIMESTAMP` column as
  `to_timestamp(epoch_us(c) / 1000000.0)` and proves, row by row against the raw copy, that
  no instant moved (`scripts/load_duckdb_real_sources.sh:138-158`): `moved` is 0 for every
  table and the probe shows 0 shifted rows (`analyses/value_parity/logs/loader.log:16-24,108-121`).
  No model or macro changed.
* **Classification.** DuckDB 1.5.5 / ext 27d85ad: the type mapping is the extension's.

### 9.3 `--same-data` could never have run on one dataset

* **Symptom.** `parity.py` had a `--same-data` flag, but every run without `--skip-build`
  started with `make duck`, whose first step reloads the fixture:
  ```
  ap.add_argument("--same-data", action="store_true",
  out = run(["make", "duck"], cwd=str(REPO), env=dbt_env())
  ```
  source: `scripts/parity.py:586,624` at `a51515d`; `docs/gaps.md:23` at `a51515d` ("no run
  has had both targets on one dataset").
* **Cause.** The flag changed only what gated; nothing changed what the DuckDB leg read. Real
  tables loaded into `dev.duckdb` would have been overwritten by the fixture before being
  measured.
* **Resolution.** `--sources real` builds with `dbt build --target duckdb` only, never
  `make duck`, and refuses to start unless `dev.duckdb` holds the real load
  (`users.user_geom` present and `orders.created_at` `TIMESTAMPTZ`,
  `scripts/parity.py:640-663,788-796`); the baseline rebuild follows the same rule
  (`scripts/parity.py:968-969`). `make value-parity` runs it end to end, with a
  `--same-data` exit 1 on the 21 differing models (`analyses/value_parity/logs/parity.log:44`).
* **Classification.** dual-target: a harness for two legs has to control what each leg reads,
  not only what gates.

## The verdict

**Sean's question: what fraction of the models run unchanged on both targets, and what does
the remainder cost per model?**

**29 of 29 models (100%) are one source file each that renders for both targets**, with no
fork, no `target.type` branch and no other engine's dialect in either render. That is what
"runs unchanged on both targets" measures here, and both targets build all 29 today. The
orchestrator measured these in this worktree on 2026-09-27 (guardrail and counts re-run for
this document):

| measurement | result |
|---|---|
| `python3 scripts/check_portability.py` | `compiled files checked: 30 (models: 29, analyses: 1)`, `BigQuery-only tokens in the DuckDB render: 0/15`, `DuckDB-only tokens in the BigQuery render: 0/13`, `target-branch findings: 0`, `PORTABLE`, exit 0 |
| `make duck` | `Finished 'build' successfully for target 'duckdb'`, `Processed: 29 models \| 167 tests`, `Summary: 196 total \| 196 success`, exit 0 |
| `make bq` (with `BQ_KEYFILE`) | `Finished 'build' with 1 warning for target 'bigquery' [2m 3s]`, `Processed: 29 models \| 167 tests`, `Summary: 196 total \| 195 success \| 1 warn`, exit 0 |
| read-only `datasets.get` on `coreychimpbot.experiments_dev` | HTTP 200, the service account listed as `OWNER` |
| `grep -rn 'target\.' models/ tests/` | one line, `models/staging/_thelook__sources.yml:17` (the allowlisted source database) |
| `git ls-files 'models/*' \| grep '.sql$' \| wc -l` | 29 |

**The remainder costs the seam.** Counted by reading the entry-macro names out of
`macros/polyglot/` and counting `<name>(` in every model file:

* **148 call sites in 29 models, mean 5.10 per model** (max 15, `stg_thelook__users`); 27
  more in `analyses/polyglot_showcase.sql`; **175** in total, the 175 that
  `move_to_duckdb.py` inlines (`docs/move_to_duckdb.md` §3).
* **25 of 29 models (86%)** call a seam macro; **4 of 29 (14%)** call none: `dim_products`,
  `dim_users`, `fct_inventory_items`, `fct_order_items`.
* 26 dialect macros (+ 52 branch macros); **16 of the 26** are called by a model.
* **1 new helper macro over 11 marts:** only `dim_date` needed `unnest_alias` (3.2), so ~1
  model in 11 demanded a new seam primitive and every other reused existing ones.
* **0 models forked for a dialect reason:** the automated DuckDB-only move edited 0 model
  files by hand and rewrote 3 non-model files (`docs/move_to_duckdb.md` §8).

**The limit that matters: "unchanged" is not "same values".** With both targets reading
the same real rows (`make value-parity`, 2026-09-27), **row counts are equal on 29 of 29
models, but only 8 of 29 match on every value, and 1 of the 11 marts (`dim_date`)**. The 21
that differ do so in 55 columns, all money except one rate derived from money: the same
`cast(x as money_type())` rounds a `FLOAT64` source value to cents on DuckDB
(`decimal(18,2)`) and keeps nine decimals on BigQuery (`numeric`,
`macros/polyglot/types.sql:85-91`). Rounding BigQuery to cents reconciles 23 of the 55;
the 32 built from cost still differ. Schema/type parity holds (0 gating mismatches), the
digest self-check passed and the DuckDB-vs-DuckDB baseline matched. The same 29 models took
19.96 s of model execution time on DuckDB and 230.25 s on BigQuery (11.5x). So "runs
unchanged" holds for 29 of 29 models; "returns the same values" holds for 8 of 29, and the
cause is one macro's type choice, not the model code. Sources:
`analyses/value_parity/results.md:11-12,52`, `analyses/value_parity/logs/parity.log:44`,
`analyses/value_parity/logs/probe_scale_attribution.log:59`; the default `make parity`
still reads the fixture and still reports 28 of 29 differing on that path
(`README.md:761-770`). The open questions are in [`gaps.md`](gaps.md) §1.

## Where each claim comes from

| claim | evidence |
|---|---|
| 1.1 core 404, community install works | `analyses/transport_a/logs/t01.log:21`; `analyses/transport_a/README.md:43-44,246-255`; `README.md:810-813` |
| 1.2 profile cannot name the community repo | `README.md:795-813`; `profiles.yml:21-41` |
| 1.3 bundled driver loads extensions, runs 1.5.4 | `README.md:814-820`; `scripts/check_env.sh:62-65,81` |
| 2.1 v2 API traps | `SPEC.md:17-35`; `NOTES.md:207,663,734-738,810-811`; `README.md:821-824,830-845`; `Makefile:134-136`; `dbt_project.yml:16-17` |
| 3.1 DECIMAL width 38 | `duckdb -c "select cast(1 as decimal(77,38))"` (2026-09-27, this worktree); `README.md:211-230` |
| 3.2 unnest alias, `TIMESTAMP[]` | `duckdb -c` reproductions above (2026-09-27); `macros/polyglot/arrays.sql:10-29,50-54,72-74`; `models/marts/dim_date.sql:18`; `README.md:299-307`; `NOTES.md:1009-1014` |
| 3.3 month-end drift | `duckdb -c` reproduction above (2026-09-27); `macros/polyglot/arrays.sql:57-60` |
| 3.4 normalisation traps | `NOTES.md:1016-1023`; `macros/polyglot/dates.sql:31,70,88,92-94`; `README.md:322-329` |
| 4.1 `safe_divide` type | `NOTES.md:1186-1196,1218`; `README.md:750-760`; `macros/polyglot/math.sql:1-25`; commit `cbe259c` |
| 5.1 three failures, 122 skipped, fourth hidden | `NOTES.md:825-889` |
| 5.2 boolean `accepted_values` | `NOTES.md:840,879-885`; `models/marts/_marts__models.yml:350-356` |
| 6.1 REST cast bug, dry-run crash | `analyses/transport_a/logs/t17.log:49`, `t18.log:29`; `analyses/transport_a/README.md:287-306` |
| 6.2 write stream `NOT_FOUND`, 5.6 / 11.3 / 128.7 s | `analyses/transport_a/README.md:234-242`; `analyses/transport_a/logs/t12b.log:12-16,36-37` |
| 6.3 `JOBS_BY_PROJECT` | `analyses/transport_a/README.md:308-312` |
| 7.1 CSV / JSON refusals | `analyses/transport_b/logs/b14.log:64`, `b13c.log:63`; `analyses/transport_b/README.md:97-99` |
| 7.2 row order | `analyses/transport_b/logs/b24.log:51-73`; `analyses/transport_b/README.md:102-130` |
| 7.3 BIGNUMERIC → double / VARCHAR | `analyses/transport_b/README.md:150,153-157`; `analyses/transport_a/README.md:173,193-199` |
| 8.1 39 findings, then excluded | `docs/move_to_duckdb.md:535,576-591`; `scripts/check_portability.py:40,254-256`; commit `60b0c5d`; `python3 scripts/check_portability.py` (2026-09-27, this worktree) |
| 8.2 `MacroSyntaxInvalid` | orchestrator's record and probe (2026-09-27, **not in a file**); `.cc-move-run3.json` |
| 9.1 `'12.30'` vs `'12.3'`, fix and self-check rows | `analyses/value_parity/logs/probe_decimal_text.log:3-5,8`; `scripts/parity.py:281-291,612-613,629-630`; commit `ba3b202` |
| 9.2 12 columns shifted -1/-2 h, mapping proved | `analyses/value_parity/logs/loader-raw-timestamps.log:120-133`; `analyses/value_parity/logs/loader.log:16-24,108-121`; `scripts/load_duckdb_real_sources.sh:138-158`; `models/staging/_thelook__sources.yml:16`; `macros/polyglot/casting.sql:49-51`; `analyses/transport_a/README.md:179` |
| 9.3 `--same-data` over `make duck` | `git show a51515d:scripts/parity.py` lines 586, 624; `git show a51515d:docs/gaps.md` line 23; `scripts/parity.py:640-663,788-796,968-969`; `analyses/value_parity/logs/parity.log:44` |
| verdict: guardrail, `make duck`, `make bq`, `datasets.get` | orchestrator's runs in this worktree, 2026-09-27; the guardrail re-run for this document; `make bq` not re-run (it costs money) |
| verdict: 148 / 5.10 / 15 / 27 / 175, 25 of 29, 16 of 26 | the counting script described above (re-run for this document); `docs/move_to_duckdb.md:77-116` |
| verdict: 0 forked, 3 rewritten, 1 helper in 11 marts | `docs/move_to_duckdb.md:447-451,509-511`; `README.md:303-307` |
| verdict: 29/29 rows, 8/29 values, marts 1/11, 55 columns, 23 reconcile at cents, 19.96 s vs 230.25 s | `analyses/value_parity/results.md:11-12,52`; `analyses/value_parity/logs/parity.log:14-44`; `analyses/value_parity/logs/probe_scale_attribution.log:59`; `analyses/value_parity/results.json`; `macros/polyglot/types.sql:85-91` |
| verdict: fixture path still 28 of 29 differ | `README.md:761-770`; `NOTES.md:1197-1203` |
