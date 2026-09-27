# Moving the project to DuckDB only: the procedure, a worked example, and the verdict

Card t_ef8e0090. Every number below has a command next to it, and the commands were
run in this worktree on 2026-09-27 (dbt-oss 2.0.5, DuckDB 1.5.5, jinja2 3.1.6, 3 CPUs).

* script: `scripts/move_to_duckdb.py` (`make move-to-duckdb`)
* worked example: `examples/duckdb_only/models/**` (`make handmove-example`)
* generated report of a move: `<out>/MOVE-REPORT.md` (not committed; `target/` is ignored)

## 1. What this is

Sean's fallback path, in his words, was *"two separate repositories and a procedure to
move code from BigQuery to DuckDB"*, the alternative to the one-project design this
repo is built on. This card builds that procedure and measures it. The short answer:
**in this project the procedure is one command.** Every dialect difference already
sits in `macros/polyglot/`, so moving to DuckDB only means inlining each macro's DuckDB
branch (175 call sites, no model edited by hand), rewriting 3 non-model files, and
building. The moved project builds green with the same 196 nodes, and its compiled SQL
is byte-identical to the source project's DuckDB compile. A fallback that cheap does
not need a second repository kept alive in advance, so the verdict (section 8) is to
**keep one project** and use this procedure when a trigger fires.

## 2. The procedure

```
uv sync                                   # jinja2 comes from the dev dependency group
.venv/bin/python scripts/move_to_duckdb.py --out DIR [--verify] [--force] [--report FILE]
.venv/bin/python scripts/move_to_duckdb.py --out DIR --manual a,b,c
.venv/bin/python scripts/move_to_duckdb.py --demo
make move-to-duckdb                       # = --out target/duckdb_only --force --verify
make handmove-example                     # section 7, end to end
```

| exit | meaning |
|---|---|
| 0 | moved (and with `--verify`, built green) |
| 1 | the moved project failed to build, or `--demo` showed the detector missed a construct |
| 2 | could not start: no `dbt_project.yml` / `macros/polyglot` at the source, jinja2 missing, `--out` exists without `--force`, or `--force` on a directory the script did not write |
| 3 | moved as far as it goes; hand-move files are outstanding (`--manual`, or a file the detector or transcoder refused) |

Every exit path prints one final `move_to_duckdb: ...` line saying what happened.

What each stage does:

1. **Absorb.** The seam macros are loaded into a jinja2 environment where
   `adapter.dispatch` always returns the `default__` (DuckDB) branch. Each `{{ ... }}`
   block in `models/**/*.sql`, `tests/**/*.sql` and `analyses/polyglot_showcase.sql`
   that calls a seam macro is rendered there and replaced by its output, as text. Every
   other Jinja block (`{{ ref() }}`, `{{ source() }}`, `{{ config() }}`, `var`,
   `env_var`, `this`, comments, `{% %}` tags) is kept byte for byte, so dbt still
   resolves the DAG. Entry macros keep their own validation, e.g. `generate_date_series`
   parses its step and `decimal_type` enforces the 38-digit ceiling. A seam call inside a
   `{% %}` tag, or one that raises, turns that file into a hand-move (exit 3).
2. **Rewrite.** The three non-model edits in section 4, applied and diffed.
3. **Detect.** It scans every moved `.sql`/`.yml` for BigQuery-only constructs (section 5),
   once on the source files and again on the moved ones.
4. **Verify** (`--verify`). It loads the fixture only if the DuckDB file is missing, then
   runs `dbt build --target duckdb` inside `<out>` with `DBT_PROFILES_DIR=<out>`. It
   asserts exit 0, `Summary: N total | N success`, no fail/error line, and processed
   models equal to moved models.
5. **Report.** `<out>/MOVE-REPORT.md`, also printed: absorbed, edited by hand, cannot
   move, verification, and an inventory of every source file with its action and reason.

**What the moved project is:** 29 models, 4 singular tests and the showcase analysis,
with **no macros**, **one target** (`duckdb`), its own `profiles.yml` and one-target
`Makefile` (`build`, `fixtures`). It reads the **same `dev.duckdb`** as the source repo,
through an absolute `path` in the emitted profile. One consequence: building the moved
project writes its tables into that file's `main` schema, where the source project's
build output lives.

## 3. Absorbed by the macro layer

These are the differences a mover does **not** have to touch. The script inlines them.
The counts describe this project today, not any other project. A project with a
different seam, or with none, will have different numbers (see the checklist in 4).

| | measured | command |
|---|---|---|
| seam | 26 dialect macros (+ 52 branch macros, `default__`/`bigquery__`) and 2 run-operation self-tests, in 10 files | `MOVE-REPORT.md`, "Absorbed" |
| call sites inlined | **175** = **148** in the 29 models + **27** in `analyses/polyglot_showcase.sql`; tests: 0 | report + the per-file table |
| cross-check | 175 entry-macro names written inside `{{ }}` blocks, equal to the rendered count | report |
| model files edited by hand | 0 | report inventory |

Per macro, over the 29 models (148 call sites):

| macro | sites | macro | sites |
|---|---:|---|---:|
| `int_type` | 51 | `month_number` | 3 |
| `string_type` | 34 | `safe_divide` | 3 |
| `money_type` | 25 | `day_of_week_iso` | 2 |
| `to_utc_timestamp` | 12 | `seconds_between` | 2 |
| `float_type` | 4 | `date_diff_days` | 1 |
| `month_start` | 4 | `format_month` | 1 |
| `generate_surrogate_key` | 3 | `generate_date_series` | 1 |
| | | `timestamp_type` | 1 |
| | | `unnest_alias` | 1 |

16 of the 26 dialect macros are called by a model and **10 are not called directly by any model**:
`generate_series`, `safe_cast`, `to_string`, `format_date_str`, `timestamp_trunc_to`,
`except_columns`, `regexp_contains`, `struct_literal`, `decimal_type`,
`type_bigint_array`. The project README says "nine". The difference is `to_string`,
which the README counts as used because the BigQuery surrogate-key branch calls it. No
model calls it directly. The README's `month_number ×4` is 3 textual occurrences in
`models/` today. Including the showcase, all 26 are called at least once. The 175
split per macro (showcase included) is in `MOVE-REPORT.md`.

Measured with the script's own inliner over `models/` only:

```
$ .venv/bin/python -c "import sys; sys.path.insert(0,'scripts'); import move_to_duckdb as m; ..."
model files 29 call sites 148
[('int_type', 51), ('string_type', 34), ('money_type', 25), ('to_utc_timestamp', 12), ('float_type', 4), ('month_start', 4), ('generate_surrogate_key', 3), ('month_number', 3), ('safe_divide', 3), ('day_of_week_iso', 2), ('seconds_between', 2), ('date_diff_days', 1), ('format_month', 1), ('generate_date_series', 1), ('timestamp_type', 1), ('unnest_alias', 1)]
not called by any model: ['generate_series', 'safe_cast', 'to_string', 'format_date_str', 'timestamp_trunc_to', 'except_columns', 'regexp_contains', 'struct_literal', 'decimal_type', 'type_bigint_array'] 10
branch macros 52
```

## 4. Edited by hand (the script does these, and shows the diff)

**1. `models/staging/_thelook__sources.yml`.** This is the one seam difference that is
not a macro (README, "Where a macro could not hide the difference", item 5). The
catalog name is derived from the source profile's DuckDB `path` (the stem of `dev.duckdb`):

```diff
-    database: "{{ 'bigquery-public-data' if target.type == 'bigquery' else target.database }}"
+    database: "dev"
```

**2. `profiles.yml`.** One output, same profile name, `path`/`schema`/`threads`;
`extensions: [httpfs, iceberg]` only (the community `bigquery` extension and the
whole `bigquery` output are removed). The file is marked as machine-written:

```yaml
# Machine-written by scripts/move_to_duckdb.py (the DuckDB-only move of
# bq_duckdb_experiments). One target, DuckDB. Regenerate rather than edit.
bq_duckdb_experiments:
  target: duckdb
  outputs:
    duckdb:
      type: duckdb
      path: /home/hermes/projects/bigquery-duckdb-dbt-experiments/.worktrees/t_ef8e0090/dev.duckdb
      schema: main
      threads: 4
      extensions:
        - httpfs
        - iceberg
```

**3. `dbt_project.yml`.** It drops `macro-paths`, because no macros ship. Model config and
`test-paths` are kept:

```diff
+# Moved to DuckDB only by scripts/move_to_duckdb.py: the seam macros were
+# inlined into the models, so this project ships no macros (macro-paths dropped).
 model-paths: ["models"]
-macro-paths: ["macros"]
 test-paths: ["tests"]
```

The script copies `models/**` yml, `tests/**`, `scripts/load_duckdb_sources.sh` and
`scripts/fixtures/**`, and emits a one-target `Makefile`. It does not move any
`analyses/transport_*/` directory. Each one is skipped as a unit and rolled up to one
inventory line: `analyses/transport_a/**` (47 files) and `analyses/transport_b/**`
(85 files: 38 SQL scenarios, 44 logs, `results.json`, `results.md`, `README.md`).
They are raw transport measurement scenarios, logs and results that need the BigQuery
community extension, GCS or Google credentials, and they are not part of the warehouse.
`macros/polyglot/**` is absorbed. The two-target tooling (`check_portability.py`,
`parity.py`, `run_bq.sh`, ...) is dropped, because it has nothing to compare in a
one-target repo.

Not rewritten: prose. `bigquery-public-data` still appears in 4 lines of the moved
project. They are a SQL comment in one singular test, a YAML comment and a description
in `_thelook__sources.yml`, and a column description in `_thelook__models.yml`. All four
document where the data comes from. None is a relation.

### The checklist for a dbt project that does NOT have this seam

The script refuses such a project (exit 2: no `macros/polyglot`). The move is then
done by hand:

1. **Find the BigQuery spellings in the render, not the source.** Run
   `dbt compile --target bigquery` and read `target/compiled/**`. Jinja, packages and
   macros are resolved there, so what you read is what the engine gets.
2. **Scan that render for the 15 BigQuery-only tokens** in `scripts/check_portability.py`
   (`BIGQUERY_ONLY`): `float64`, `safe_cast`, `safe_divide`, `generate_array`,
   `generate_date_array`, `regexp_contains`, `format_date`, `timestamp_trunc`,
   `timestamp_diff`, `bignumeric`, `struct(`, `* except (`, `array<`, `date_diff(` not
   followed by a quote, `bigquery-public-data`. This is a starting point, not a
   complete list. Types like `int64`/`string` also need a decision, and DuckDB
   accepts `int64` but not `float64`.
3. **Translate each hit with the table in the project README** ("The macro layer":
   DuckDB render next to BigQuery render). Watch the non-renames: `date_diff` argument
   order, `format_date` format-first, `WEEK` = Sunday, `DAYOFWEEK` numbering,
   `SAFE_DIVIDE`'s result type, the `unnest` alias, and `generate_date_array` returning
   `DATE`s.
4. **Sources**: replace every BigQuery `database`/`project` with the DuckDB catalog.
   **Profile**: one `type: duckdb` output.
5. **Search the source for the "cannot move" list in section 5**, by eye or with
   `detect()` from `scripts/move_to_duckdb.py`. Decide for each hit whether to drop
   it or to fork that model.
6. **Build on DuckDB and compare**: the same tests green, and if both engines can read
   the same data, `scripts/parity.py`.

## 5. Cannot move at all

These are BigQuery-only constructs that nothing in the seam covers. The detector looks
for all of them. Findings are `file:line: [rule] matched text -> line`, with SQL
comments, `{# #}` and YAML comments stripped:

| rule | construct |
|---|---|
| `partition_by` | dbt `partition_by` config |
| `cluster_by` | dbt `cluster_by` config |
| `external_table` | external tables: `external_location`, `uris`, `format = parquet/csv/...` |
| `table_options` | `OPTIONS(...)` |
| `bq_script` | BigQuery scripting: `BEGIN ... END`, `CREATE PROCEDURE`, `DECLARE` |
| `storage_api` | Storage Write/Read API |
| `geography` | `GEOGRAPHY`, `ST_GEOG*` |
| `bignumeric` | `BIGNUMERIC`/`BIGDECIMAL`, or any `numeric`/`decimal`/`decimal_type` wider than 38 digits |
| `bqml` | `ML.PREDICT(...)` and friends, `CREATE MODEL` |
| `safe_offset` | `SAFE_OFFSET`/`SAFE_ORDINAL` (and `[OFFSET(n)]`/`[ORDINAL(n)]`) |
| `with_offset` | `UNNEST ... WITH OFFSET` |
| `target_branch` | `target.type`, `target.name`, `adapter.type` (any branch on the target) |

**In this project:** the source has **1 finding**:
`models/staging/_thelook__sources.yml:17: [target_branch] target.type`, the
`database:` line. Rewrite 1 resolves it. The moved project, re-scanned after the move,
has **0 findings**.

**It fires.** `--demo` writes `models/intermediate/_move_demo.sql` with 12 construct
kinds, runs the detector, deletes the file in a `finally`, and checks that `git status`
is unchanged:

```
$ .venv/bin/python scripts/move_to_duckdb.py --demo
demo: wrote models/intermediate/_move_demo.sql with 12 injected construct kinds

  models/intermediate/_move_demo.sql:3: [partition_by] `partition_by=` -> {{ config(materialized='table', partition_by={'field': 'order_date', 'data_type': 'date'},
  models/intermediate/_move_demo.sql:4: [cluster_by] `cluster_by=` -> cluster_by=['user_id'], external_location='gs://bucket/orders/*', submission='storage_write_api') }}
  models/intermediate/_move_demo.sql:4: [external_table] `external_location` -> cluster_by=['user_id'], external_location='gs://bucket/orders/*', submission='storage_write_api') }}
  models/intermediate/_move_demo.sql:4: [storage_api] `storage_write_api` -> cluster_by=['user_id'], external_location='gs://bucket/orders/*', submission='storage_write_api') }}
  models/intermediate/_move_demo.sql:7: [bignumeric] `bignumeric` -> cast(o.total as bignumeric)             as total_big,
  models/intermediate/_move_demo.sql:8: [geography] `geography` -> cast(null as geography)                 as shipped_to,
  models/intermediate/_move_demo.sql:9: [safe_offset] `safe_offset(` -> o.items[safe_offset(0)]                 as first_item,
  models/intermediate/_move_demo.sql:12: [with_offset] `with offset` -> cross join unnest(o.items) as item with offset as pos
  models/intermediate/_move_demo.sql:13: [target_branch] `target.type` -> {% if target.type == 'bigquery' %}where true{% endif %}
  models/intermediate/_move_demo.sql:15: [table_options] `options(` -> create or replace table demo options(description = 'demo') as
  models/intermediate/_move_demo.sql:16: [bqml] `ml.predict(` -> select * from ml.predict(model demo_model, (select 1 as x));
  models/intermediate/_move_demo.sql:17: [bq_script] `begin` -> begin
  models/intermediate/_move_demo.sql:18: [bq_script] `create procedure` -> create procedure demo_proc() begin select 1; end;

demo: removed models/intermediate/_move_demo.sql
demo: detector found 12/12 construct kinds
demo: re-check: models/intermediate/_move_demo.sql exists=False, models/ findings now 0, git status unchanged
move_to_duckdb --demo: the detector found every injected construct; tree left as found (exit 0)
```

**It is a blacklist, not a proof.** It is regular expressions over text. A construct
spelled in a way the patterns miss, or hidden in a macro or package the scan does not
read (it scans moved files, not `macros/` or `dbt_packages/`), passes silently. It
also matches words, so a column named `geography` would be a false positive. Zero
findings means "none of these 12 kinds was spelled the way the patterns expect". The
real proof that a move worked is section 6.

## 6. How to verify a moved project

**Build green with the same tests.** The source first, then the move:

```
$ make duck
Finished 'build' successfully for target 'duckdb' [4.5s]
Processed: 29 models | 167 tests
Summary: 196 total | 196 success

$ .venv/bin/python scripts/move_to_duckdb.py --out target/duckdb_only --force --verify
...
Finished 'build' successfully for target 'duckdb' [3.8s]
Processed: 29 models | 167 tests
Summary: 196 total | 196 success
Result: PASS: exit 0, 196 total | 196 success, no fail/error line, 29 models processed = 29 moved
move_to_duckdb: moved into .../target/duckdb_only (...); 175 call sites inlined; build green: ... (exit 0)

$ make move-to-duckdb
.../.venv/bin/python scripts/move_to_duckdb.py --out target/duckdb_only --force --verify
Processed: 29 models | 167 tests
Summary: 196 total | 196 success
move_to_duckdb: ... build green: exit 0, 196 total | 196 success, ... (exit 0)
```

**Compiled SQL byte-identical to the source project.** Both builds write
`target/compiled/`. The source compiles with the macros, the moved project without them:

```
$ diff -r -x '*.json' target/compiled/bq_duckdb_experiments/models \
      target/duckdb_only/target/compiled/bq_duckdb_experiments/models     # no output, exit 0
$ diff -r -x '*.json' target/compiled/bq_duckdb_experiments/tests \
      target/duckdb_only/target/compiled/bq_duckdb_experiments/tests      # no output, exit 0
```

That covers 29/29 compiled models and 4/4 singular tests. (`-x '*.json'` skips dbt's
`*.macro_spans.json` sidecars, which record where macros expanded and so differ by design.)

**Nothing of the seam is left:** there is no `default__`, `adapter.dispatch`, `bigquery__`
or `target.type` anywhere under the moved `models/`, `tests/` or `analyses/`. The only
Jinja left there is `{{ ref` ×55, `{{ source` ×7 and `{{ config` ×1
(`grep -rhoE '\{\{ *[a-z_]+' target/duckdb_only/{models,tests,analyses} | sort | uniq -c`).

## 7. The worked example: three real models moved by hand

The orchestrator chose three models: `stg_thelook__orders` (`int_type`, `string_type`,
`to_utc_timestamp`), `dim_date` (the hardest: `unnest_alias`, `generate_date_series`,
`month_start` with `timestamp_type` nested in its argument, `format_month`,
`day_of_week_iso` ×2, `date_diff_days`, `int_type` ×5, `string_type`) and
`mart_daily_revenue` (`money_type`). Each was written by hand into
`examples/duckdb_only/models/...` from the macro docstrings in `macros/polyglot/`,
with the original comments and column layout kept. Each file starts with two header
lines prefixed `-- [hand-moved]`.

**How blind it was.** For `stg_thelook__orders` and `mart_daily_revenue` I had not seen
the transcoder's output before writing them. For `dim_date` I had: while building the
script I diffed the moved `dim_date` and read its `--manual` placeholder, which lists
every rendering. So `dim_date` counts as a checked hand-move, not an independent one.

**It is a real hand-move** (`diff <source> <example>`, unedited):

```
$ diff models/staging/stg_thelook__orders.sql examples/duckdb_only/models/staging/stg_thelook__orders.sql
0a1,2
> -- [hand-moved] Worked example (card t_ef8e0090): models/staging/stg_thelook__orders.sql
> -- [hand-moved] moved to DuckDB-only SQL by hand from the macro docstrings in macros/polyglot/.
10,18c12,20
<         cast(order_id as {{ int_type() }})                  as order_id,
<         cast(user_id as {{ int_type() }})                   as user_id,
<         cast(status as {{ string_type() }})       as status,
<         cast(gender as {{ string_type() }})       as gender,
<         {{ to_utc_timestamp('created_at') }}      as created_at,
<         {{ to_utc_timestamp('returned_at') }}     as returned_at,
<         {{ to_utc_timestamp('shipped_at') }}      as shipped_at,
<         {{ to_utc_timestamp('delivered_at') }}    as delivered_at,
<         cast(num_of_item as {{ int_type() }})               as num_of_item
---
>         cast(order_id as bigint)                  as order_id,
>         cast(user_id as bigint)                   as user_id,
>         cast(status as varchar)       as status,
>         cast(gender as varchar)       as gender,
>         timezone('UTC', cast(created_at as timestamptz))      as created_at,
>         timezone('UTC', cast(returned_at as timestamptz))     as returned_at,
>         timezone('UTC', cast(shipped_at as timestamptz))      as shipped_at,
>         timezone('UTC', cast(delivered_at as timestamptz))    as delivered_at,
>         cast(num_of_item as bigint)               as num_of_item

$ diff models/marts/dim_date.sql examples/duckdb_only/models/marts/dim_date.sql
0a1,2
> -- [hand-moved] Worked example (card t_ef8e0090): models/marts/dim_date.sql
> -- [hand-moved] moved to DuckDB-only SQL by hand from the macro docstrings in macros/polyglot/.
18c20
<     cross join unnest({{ generate_date_series('first_date', 'last_date') }}) as {{ unnest_alias('date_day') }}
---
>     cross join unnest(cast(generate_series(first_date, last_date, interval 1 day) as date[])) as date_day__unnest(date_day)
24,31c26,33
<     cast({{ format_month('date_day') }} as {{ string_type() }})         as date_month,
<     {{ month_start('cast(date_day as ' ~ timestamp_type() ~ ')') }}     as month_start_at,
<     cast(extract(year from date_day) as {{ int_type() }})               as year_number,
<     cast(extract(month from date_day) as {{ int_type() }})              as month_of_year,
<     cast(extract(day from date_day) as {{ int_type() }})                as day_of_month,
<     cast({{ day_of_week_iso('date_day') }} as {{ int_type() }})         as day_of_week_iso,
<     {{ day_of_week_iso('date_day') }} >= 6                              as is_weekend,
<     cast({{ date_diff_days('date_day', 'first_date') }} as {{ int_type() }})
---
>     cast(strftime(date_day, '%Y-%m') as varchar)         as date_month,
>     cast(date_trunc('month', cast(date_day as timestamp)) as timestamp)     as month_start_at,
>     cast(extract(year from date_day) as bigint)               as year_number,
>     cast(extract(month from date_day) as bigint)              as month_of_year,
>     cast(extract(day from date_day) as bigint)                as day_of_month,
>     cast(extract(isodow from date_day) as bigint)         as day_of_week_iso,
>     extract(isodow from date_day) >= 6                              as is_weekend,
>     cast(date_diff('day', first_date, date_day) as bigint)

$ diff models/marts/mart_daily_revenue.sql examples/duckdb_only/models/marts/mart_daily_revenue.sql
0a1,2
> -- [hand-moved] Worked example (card t_ef8e0090): models/marts/mart_daily_revenue.sql
> -- [hand-moved] moved to DuckDB-only SQL by hand from the macro docstrings in macros/polyglot/.
11c13
<     cast(round(gross_revenue / nullif(order_count, 0), 2) as {{ money_type() }})
---
>     cast(round(gross_revenue / nullif(order_count, 0), 2) as decimal(18,2))
```

**It equals the automatic move.** Move with the three left for a hand move, drop the
examples over the placeholders, and compare against the automatic copy:

```
$ .venv/bin/python scripts/move_to_duckdb.py --out target/handmove --force \
      --manual dim_date,stg_thelook__orders,mart_daily_revenue          # exit 3
Outstanding hand-move files:
  .../target/handmove/models/marts/dim_date.sql
  .../target/handmove/models/marts/mart_daily_revenue.sql
  .../target/handmove/models/staging/stg_thelook__orders.sql
move_to_duckdb: moved into .../target/handmove (...); 3 hand-move file(s) outstanding, 151 call sites inlined elsewhere (exit 3)

$ cp examples/duckdb_only/models/... target/handmove/models/...          # the three files

$ diff -w -I '^-- \[hand-moved\]' target/handmove/<f> target/duckdb_only/<f>   # all three: no output
$ diff target/handmove/<f> target/duckdb_only/<f>                             # all three: only the header
1,2d0
< -- [hand-moved] Worked example (card t_ef8e0090): models/marts/dim_date.sql
< -- [hand-moved] moved to DuckDB-only SQL by hand from the macro docstrings in macros/polyglot/.
```

The plain diff of each file shows only its own two header lines. There are no token
differences, and not even whitespace differences, because the hand-move kept the
source layout and each macro is replaced in place. (151 = 175 − 24, the call sites of
the three hand-moved models: 9 + 14 + 1.)

**It builds green.** The moved project's own Makefile runs
`DBT_PROFILES_DIR=$(CURDIR) $(DBT) build --target duckdb`:

```
$ make -C target/handmove build
.../.venv/bin/dbt build --target duckdb
Finished 'build' successfully for target 'duckdb' [3.7s]
Processed: 29 models | 167 tests
Summary: 196 total | 196 success
```

**End to end, and it fails loudly.** `make handmove-example` does the steps above into
`target/handmove_example`, with the automatic copy in `target/handmove_example_auto`:

```
$ make handmove-example
handmove-example: 3/3 hand-moved models equal the automatic transcode (diff -w); build green: Processed: 29 models | 167 tests | Summary: 196 total | 196 success
```

With `decimal(18,2)` changed to `decimal(18,3)` in the example `mart_daily_revenue`
(and changed back afterwards):

```
13c11
<     cast(round(gross_revenue / nullif(order_count, 0), 2) as decimal(18,3))
---
>     cast(round(gross_revenue / nullif(order_count, 0), 2) as decimal(18,2))
handmove-example: FAIL models/marts/mart_daily_revenue.sql differs from the automatic transcode
make: *** [Makefile:103: handmove-example] Error 1
```

## 8. The verdict: one project with transcoding macros, or two repos with a procedure?

**What one project costs today (measured).** 29 models; 148 seam call sites inside
them; 26 dialect macros (52 branch macros); 0 forked models; 0 model files edited by
hand in the automated move; 3 non-model files rewritten by it. Of the 5 differences the
seam had to work around (README, "Where a macro could not hide the difference"),
exactly one is not a macro: the source `database:` line. Card 4's parity harness
compared all 29 models on both targets and found **1 real type divergence (1/29)**,
`mart_product_performance.gross_margin_rate`. It has since been fixed (README, "What
is NOT verified").

**What the fallback costs (measured).** One command moves the whole project and builds
it green: `move_to_duckdb.py --out target/duckdb_only --force --verify` took
**4.74 s** and **4.78 s** wall time on two runs, the dbt build included
(`Finished 'build' ... [3.8s]` both times). The result compiles byte-identical to the
source (29/29 models, 4/4 singular tests), and a hand-move of three models lands on the
same SQL as the automatic one.

**The marginal cost of a new model in one project (from the project's history, not
measured by this card).** Per the README and card 3, `dim_date`, the eleventh mart, is
the one model that needed a *new* helper macro (`unnest_alias`, for a difference in the
`FROM` alias). Every other model reused existing macros. The README records nine of the
26 dialect macros as not needed by any model; they are covered by the self-check and
the showcase instead. This card measures ten, because `to_string` is only reached
through the BigQuery surrogate-key branch (section 3). So most of the seam was built
ahead of demand, and a new model usually costs zero new macros.

**What two repos cost.** Two profiles, two source declarations and two test runs to
keep in step, plus drift that only a comparison catches. The parity harness exists
because of drift, and it found a divergence *inside one project with a shared model
tree*. Two repos with hand-copied models would give drift more room. **Not measured
here:** how often a two-repo setup drifts. This card did not run one over time.

**What two repos buy.** The BigQuery repo can use what DuckDB cannot: partitioning,
clustering, external tables, the Storage Write API, BQML, `GEOGRAPHY`, `BIGNUMERIC`
beyond 38 digits. A one-project design must drop those or special-case them. The DuckDB
repo can read whatever DuckDB reads (local files, Iceberg, `httpfs`) without asking
whether BigQuery could. **Today this project uses none of the BigQuery-only list:** the
detector finds 0 constructs apart from the rewritten `database:` line.

**The data question does not force a split.** A two-repo design is sometimes argued
from data access: "the DuckDB leg cannot see BigQuery data". `analyses/transport_a/`
measured the opposite in this tree. DuckDB 1.5.5 reads BigQuery through the community
extension, and t14 materialised the whole 5,552,452-row `usa_names.usa_1910_2013`
table locally in 11.7 s (11.2 s, 11.9 s and 22.2 s in other runs). Card 6 measured the
`EXPORT DATA` → Parquet route on PR #9. That PR is now merged, and the measurement is in
this tree as `analyses/transport_b/`. This card did not re-run it, so none of its
numbers are quoted here. With either route, DuckDB can be given BigQuery's data without
splitting the code.

**Switch to two repos when any of these happens:**

* A model needs a construct from the "cannot move" list that cannot be dropped:
  partitioning or clustering that real BigQuery cost depends on, BQML, external tables,
  or Storage Write. Concretely: the detector reports a finding that is not the source
  line, and the fix is not "delete it".
* A difference stops fitting in an expression macro, like the source `database:` line
  did. That shows up as a `{% %}` branch on the target in a model (the guardrail and
  the detector both fail on it), or as models that exist on one target only.
* The DuckDB leg starts depending on DuckDB-only sources or features that BigQuery
  will never have, so the two DAGs diverge rather than the two dialects.
* The parity harness keeps finding divergences that need model-level rather than
  macro-level fixes.

**Keep one project while all of these hold:** the detector stays at 0 findings beyond the
source line; the parity harness gates green on types; new models reuse the seam (so far
1 new helper macro in 11 marts); and `make move-to-duckdb` stays green and
byte-identical. That last check makes the fallback an insurance policy that can be
tested on every change.

**Recommendation: keep one project with the transcoding macros, and treat
`make move-to-duckdb` as the tested, one-command exit to a DuckDB-only repository, to be
taken the day a model needs something on the "cannot move" list.**

### Numbers and where they came from

| number | where it came from |
|---|---|
| 29 models, 167 tests, 196 total / 196 success (source) | `make duck` (this run) |
| 29 models, 167 tests, 196 / 196 (moved) | `.venv/bin/python scripts/move_to_duckdb.py --out target/duckdb_only --force --verify`; `make move-to-duckdb` |
| 29 models, 167 tests, 196 / 196 (hand-moved) | `make -C target/handmove build`; `make handmove-example` |
| 4.74 s, 4.78 s wall (move + build); dbt `[3.8s]` both runs | `time .venv/bin/python scripts/move_to_duckdb.py --out target/duckdb_only --force --verify` (two runs) |
| 29/29 models and 4/4 singular tests byte-identical | `diff -r -x '*.json'` of the two `target/compiled/.../{models,tests}` trees (section 6) |
| 26 dialect macros, 52 branch macros, 2 self-tests, 10 files | `MOVE-REPORT.md` "Absorbed" and the inliner one-liner in section 3 |
| 175 call sites = 148 (models) + 27 (showcase), 0 in tests | `MOVE-REPORT.md` per-file table; the inliner one-liner over `models/` |
| per-macro counts over the models | the inliner one-liner in section 3 |
| 10 dialect macros not called directly by a model | the inliner one-liner in section 3 |
| 9 not called (README) | project README, "The macro layer" (card 3), not re-measured |
| 3 files rewritten, 0 model files hand-edited, 167 skipped, 11 copied, 34 transcoded, 1 generated | `MOVE-REPORT.md` inventory totals (after the rebase onto `76d83cb`; 73 skipped before it) |
| 47 files in `analyses/transport_a/`, 85 in `analyses/transport_b/` (38 SQL, 44 logs, 3 other) not moved | `MOVE-REPORT.md` inventory roll-up lines |
| guardrail: 90 compiled files (29 models, 61 analyses), 39 findings (12 in `transport_a`, 27 in `transport_b`), 0 in models | `python3 scripts/check_portability.py` (after the rebase; 52 files / 12 findings before it). **Resolved afterwards:** the guardrail now excludes `analyses/transport_a` and `analyses/transport_b` from the scan |
| detector: 1 finding in source (resolved), 0 after the move | `MOVE-REPORT.md` "Cannot move at all" |
| 12/12 injected construct kinds found | `.venv/bin/python scripts/move_to_duckdb.py --demo` |
| 151 call sites inlined with 3 models hand-moved | `--manual dim_date,stg_thelook__orders,mart_daily_revenue` final line |
| `{{ ref` ×55, `{{ source` ×7, `{{ config` ×1 left | `grep -rhoE '\{\{ *[a-z_]+' ... \| sort \| uniq -c` (section 6) |
| 5 seam workarounds, 1 not a macro | project README, "Where a macro could not hide the difference" (card 3) |
| 1/29 type divergence, since fixed | project README, "What is verified" / "What is NOT verified" (card 4, fixed by card 7) |
| `dim_date` = the model that needed `unnest_alias` | project README, "Where a macro could not hide the difference" item 3 (card 3) |
| 5,552,452 rows in 11.7 s (11.2 / 11.9 / 22.2 s) | `analyses/transport_a/README.md`, t14 (the Transport A card), not re-run |
| card 6 / PR #9 | merged, in the tree as `analyses/transport_b/`; **not re-run** by this card, no number quoted |
| how often two repos drift | **not measured** |

## 9. What is NOT verified

* **Only this project.** The absorb step needs the `macros/polyglot/` seam shape
  (entry → `adapter.dispatch` → `default__`). A project without it gets exit 2 and the
  manual checklist in section 4, and that checklist has not been run on another project.
* **The detector is a blacklist.** It is regular expressions over the moved files
  (section 5). A construct outside its 12 kinds, or spelled differently, or inside a
  macro/package, is not reported. Zero findings is not proof of portability. The green
  build and the byte-identical compile are the proof for *this* move.
* **The textual inliner has limits it refuses rather than handles.** A seam call inside
  a `{% %}` tag, e.g. `{% set x = safe_cast(...) %}`, becomes a hand-move. A `}}`
  inside a string literal in a Jinja expression would split a block wrongly. Neither
  occurs in this project.
* **The moved project is not independent of the source checkout.** Its profile points at
  the source repo's `dev.duckdb` by absolute path, and its `Makefile` uses the source
  repo's `.venv/bin/dbt`. Building it overwrites the source build's tables in that file.
  Making it standalone means editing `path` and `DBT`. That standalone setup is not exercised.
* **Only the DuckDB fixture.** Every build above reads the generated fixture, not the
  real `thelook_ecommerce`. Byte-identical SQL means the moved project would read real
  data exactly as the source does on DuckDB, but that was not run.
* **The worked example is only partly blind.** `dim_date` was written after its
  automatic rendering had been seen (section 7). The two other models were not.
* **The two-repo side of the verdict is argued, not measured.** No two-repo setup was
  run over time. Drift frequency and the upkeep of two profiles and two test runs are
  estimated from this repo's history (the parity harness and its 1/29 finding), not
  counted.
* **Card 6 / PR #9 is cited, not re-run.** The `EXPORT DATA` → Parquet route is merged
  and in this tree as `analyses/transport_b/`, but this card did not re-run it or check
  its numbers, so none are quoted.
* **The two-target guardrail was red at this measurement, and was before this card
  (measured by the orchestrator); it was fixed afterwards** by excluding
  `analyses/transport_a` and `analyses/transport_b` from the scan, and `make portability`
  is green again. At this measurement `make portability` and `make polyglot` failed on
  this repository, and did so before this card: the 12 findings are all in
  `analyses/transport_a/sql/t15..t17*.sql`, whose SQL is deliberately
  BigQuery-flavoured, and dbt parses those scenarios as analyses. Measured identically
  on a clean checkout of `35f3ba0` (the base commit). It is a pre-existing defect in the
  guardrail's scope, filed separately; it is not caused by the move, and a moved
  DuckDB-only project has no such file.
  **Update after the rebase onto `76d83cb` (PR #9, Transport B):** the same scope
  defect now covers Transport B too. `python3 scripts/check_portability.py` reports
  `compiled files checked: 90 (models: 29, analyses: 61)` and
  `NOT PORTABLE: 39 finding(s)`. That is 12 in `analyses/transport_a/sql/` (unchanged)
  and 27 in `analyses/transport_b/sql/`, with 0 in `models/` and 0 in
  `analyses/polyglot_showcase.sql`. Before the rebase it was 52 files / 12 findings.
