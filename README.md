# bigquery-duckdb-dbt-experiments

One dbt v2 project, two targets. The same models are built against **BigQuery**
and against a local **DuckDB** file, with the dialect differences pushed into
`macros/` rather than into a forked model tree. Sean's framing: *"one single
project power both with using macros to help transpile."*

**Status: a 29-model warehouse over `thelook_ecommerce`, built and tested on
DuckDB only, with every dialect difference in `macros/polyglot/`.** The model
tree is the one described in `SPEC.md`: 7 staging views, 11 intermediate views and
11 mart tables over the 7 tables of Google's public
`bigquery-public-data.thelook_ecommerce` dataset. On the `duckdb` target the whole
tree builds and 168 tests pass, twice in a row. That run reads a **generated
fixture**: invented data with the real schema, not the real dataset (see "The
DuckDB fixture"). On the `bigquery` target the project compiles and parses. **It
never runs there:** this machine has no Google credentials.

The transpile seam is **28 macros** in `macros/polyglot/`, one per dialect
difference, each dispatching on the adapter; the DuckDB branch of every one of them
is **executed** against DuckDB by `make polyglot` (44 self-check cases), and their
BigQuery branch is rendered and inspected but never run. `scripts/check_portability.py`
is the guardrail that turns "portable" into a number: it compiles both targets and
scans each render for the other engine's dialect (0 findings over 30 compiled
files, plus 0 target branches in `models/`), and `--demo` shows it failing on
purpose. See "The macro layer" below.

## Layout

```
dbt_project.yml         dbt v2 project (no config-version; v2 does not use it)
profiles.yml            BOTH targets, committed — it holds no credentials
packages.yml            empty on purpose: every package must work on both targets
pyproject.toml + uv.lock  dbt itself, pinned (dbt-oss 2.0.5)
Makefile                make setup | check-env | fixtures | duck | bq | build-both | parity |
                        polyglot | portability | clean
models/staging/         7 views: rename + cast only, one per source table; the source definition
models/intermediate/    11 views: the joins and aggregates
models/marts/           11 tables: fct_*, dim_*, mart_* (dim_date is the date spine)
macros/polyglot/        the transpile seam: 28 macros, one per dialect difference
analyses/               polyglot_showcase.sql: one query calling every macro (compiled, never run)
tests/                  3 singular tests (cross-model invariants)
scripts/check_env.sh    prerequisite gate; fails loudly, never half-succeeds
scripts/install_prereqs.sh  dbc, the DuckDB driver, the DuckDB CLI, the community extension
scripts/load_duckdb_sources.sh  loads the DuckDB fixture and checks its integrity (make fixtures)
scripts/fixtures/       the fixture generator SQL, plus the grain/coherence check queries
scripts/check_portability.py  the guardrail: compile both targets, scan each render for the
                        other dialect, fail on a target branch in a model (make portability)
scripts/polyglot_check.sh  the macro layer end to end (make polyglot)
scripts/run_bq.sh       the BigQuery leg: refuses clearly when credentials are absent
scripts/parity.py       every model, both targets: rows, names, types, per-column checksums
                        (make parity)
SPEC.md                 the design contract for the model tree
NOTES.md                the build record: every decision, deviation and command output
```

`seeds/` is deliberately absent. The DuckDB fixture is generated SQL loaded out of
band, not a seed, so that the BigQuery target can never receive fixture data.

## The models

The source is one definition, `thelook_ecommerce`, in
`models/staging/_thelook__sources.yml`. Its database is target-dependent:

```yaml
database: "{{ 'bigquery-public-data' if target.type == 'bigquery' else target.database }}"
schema: thelook_ecommerce
```

On `bigquery` the models read `bigquery-public-data.thelook_ecommerce.<table>`, which
is the real public data. On `duckdb` they read `dev.thelook_ecommerce.<table>`, the
local fixture. No model knows which target it is on. Every dialect difference
(types, time zones, month truncation, date diffs, array generators, struct
literals, regular expressions, safe division, surrogate-key hashing) is a
dispatched macro in `macros/polyglot/` — see "The macro layer" below.

| layer | models | materialised | what it does |
|---|---|---|---|
| staging | `stg_thelook__{orders,order_items,users,products,inventory_items,distribution_centers,events}` | view | rename (`id` → `<entity>_id`) and cast; no joins |
| intermediate | `int_order_items__enriched`, `int_orders__item_rollup`, `int_orders__daily`, `int_users__lifetime_orders`, `int_users__first_order_cohort`, `int_cohorts__user_months`, `int_products__sales`, `int_products__returns`, `int_inventory_items__enriched`, `int_inventory__by_product_center`, `int_events__sessions` | view | joins and aggregates; grain stated per model |
| marts | `fct_orders`, `fct_order_items`, `fct_inventory_items`, `dim_users`, `dim_products`, `dim_distribution_centers`, `dim_date`, `mart_daily_revenue`, `mart_product_performance`, `mart_customer_summary`, `mart_cohort_retention` | table | facts, dimensions and aggregates |

`dim_date` is the date spine (card 3): one row per UTC calendar date from the first
to the last order date, 1415 rows on the fixture, built with `generate_date_series`,
`day_of_week_iso`, `format_month`, `month_start` and `date_diff_days`. It is what
makes the date macros load-bearing rather than dead code, and
`mart_daily_revenue.revenue_date` has a `relationships` test against it.


Conventions, all stated in the model docs:

* Money is `money_type()`: `decimal(18,2)` on DuckDB, `numeric` on BigQuery. The currency is **USD**.
* Rates are `float_type()` (`double` / `float64`).
* Every `*_at` column is a **naive UTC timestamp**. BigQuery TIMESTAMP arrives in DuckDB
  as TIMESTAMPTZ, and a plain cast would apply the session time zone.
* "Gross" means every order item, whatever its status. Returns are separate columns.
* Surrogate keys are used only where the grain has no natural key: user × month,
  product × center, and cohort × activity month.

Every model and every column has a description. The tests are 165 generic tests
(`unique`/`not_null` on every key, `not_null` on every foreign key, `relationships`
across the marts, `accepted_values` on status/gender/traffic_source/event_type/department)
and 3 singular tests — 197 build nodes in total (`29 models | 168 tests`).

## The macro layer (`macros/polyglot/`)

**28 macros** — 26 dialect macros plus 2 `run-operation` macros that test them. Each
dialect macro is an entry point that does
`{{ return(adapter.dispatch('<name>', 'bq_duckdb_experiments')()) }}` with a
`default__` (DuckDB) branch and a `bigquery__` branch (52 branch macros in all), and a
`{# … #}` docstring that says what it does and **why the two dialects differ**. The
dispatch is on the adapter's type, which is the same value as `target.type` on both
targets, so this is "dispatching on `target.type`" with dbt's own mechanism. No model,
analysis or test contains a target branch: that is what the guardrail below enforces.

| file | macros |
|---|---|
| `types.sql` | `int_type`, `string_type`, `float_type`, `timestamp_type`, `money_type`, `decimal_type(p,s)`, `type_bigint_array` |
| `casting.sql` | `safe_cast`, `to_string`, `to_utc_timestamp` |
| `selection.sql` | `except_columns` |
| `structs.sql` | `struct_literal` |
| `arrays.sql` | `generate_series`, `generate_date_series`, `unnest_alias` |
| `dates.sql` | `date_diff_days`, `format_date_str`, `format_month`, `timestamp_trunc_to`, `day_of_week_iso`, `month_start`, `month_number`, `seconds_between` |
| `math.sql` | `safe_divide` |
| `strings.sql` | `regexp_contains` |
| `keys.sql` | `generate_surrogate_key` |
| `self_check.sql` | `polyglot_render`, `polyglot_selfcheck` (the macro layer's own tests) |

`unnest(...)` is deliberately **not** wrapped — the name and semantics are the same on
both engines. What differs is the alias in `FROM`, and that needed a macro of its own:
see "where a macro could not hide the difference" below.

`dbt run-operation polyglot_render --target <t>` prints every macro's rendering for
that target (the two files `target/polyglot_render_<target>.txt` after `make polyglot`
are exactly those renders). Measured on this machine:

| macro | DuckDB render | BigQuery render | why the dialects differ | called by a model |
|---|---|---|---|---|
| `int_type()` | `bigint` | `int64` | BigQuery has one integer type, INT64; DuckDB's canonical 64-bit int is BIGINT | `int_type` ×51 in 18 models |
| `string_type()` | `varchar` | `string` | DuckDB keeps the SQL-standard name; BigQuery has no VARCHAR | ×34 |
| `float_type()` | `double` | `float64` | as above | ×4 |
| `timestamp_type()` | `timestamp` | `timestamp` | same name, different meaning (`to_utc_timestamp`) | `dim_date` |
| `money_type()` | `decimal(18,2)` | `numeric` | BigQuery NUMERIC is fixed 38,9; DuckDB needs an explicit width/scale | ×25 |
| `decimal_type(p,s)` | `decimal(p,s)`, compiler error when `p > 38` | `numeric` when `s <= 9`, else `bignumeric` | DuckDB DECIMAL stops at 38 digits (rule below) | no — self-check + render |
| `type_bigint_array()` | `bigint[]` | `array<int64>` | DuckDB writes `T[]`, BigQuery the parameterised `ARRAY<T>` | no — self-check + render |
| `safe_cast(expr, type)` | `try_cast('42' as bigint)` | `safe_cast('42' as int64)` | same semantics, different name | no — self-check + render |
| `to_string(expr)` | `cast(user_id as varchar)` | `cast(user_id as string)` | via `string_type()` | (used by the BigQuery surrogate-key branch) |
| `to_utc_timestamp(expr)` | `timezone('UTC', cast(created_at as timestamptz))` | `cast(created_at as timestamp)` | BigQuery TIMESTAMP is an instant; DuckDB hands it back as TIMESTAMPTZ | ×12 |
| `except_columns(cols)` | `* exclude (a, b)` | `* except (a, b)` | BigQuery calls the star modifier EXCEPT, DuckDB EXCLUDE | no — self-check + render |
| `struct_literal(fields)` | `{'a': 1, 'b': 2}` | `struct(1 as a, 2 as b)` | named-field constructor vs map-like literal (field access `s.a` is the same on both) | no — self-check + render |
| `generate_series(a, b[, step])` | `generate_series(1, 9, 3)` | `generate_array(1, 9, 3)` | different generator names, same inclusive semantics | no — self-check + render |
| `generate_date_series(a, b, step)` | `cast(generate_series(…, interval 1 day) as date[])` | `generate_date_array(…, interval 1 day)` | BigQuery returns ARRAY<DATE>; DuckDB's date series is TIMESTAMP[] | `dim_date` |
| `unnest_alias(col)` | `date_day__unnest(date_day)` | `date_day` | DuckDB binds a FROM alias to the table, BigQuery to the element | `dim_date` |
| `date_diff_days(later, earlier)` | `date_diff('day', earlier, later)` | `date_diff(later, earlier, day)` | the arguments are **reversed** between the engines | `dim_date` |
| `format_date_str(expr, fmt)` | `strftime(expr, '%Y/%m/%d')` | `format_date('%Y/%m/%d', expr)` | different function **and** the format argument comes first on BigQuery | no — self-check + render |
| `format_month(expr)` | `strftime(expr, '%Y-%m')` | `format_date('%Y-%m', expr)` | the one format the marts need | `dim_date` |
| `timestamp_trunc_to(expr, g)` | `date_trunc('hour', expr)` | `timestamp_trunc(expr, hour)` | BigQuery's part is a bare keyword, DuckDB's a quoted string | no — self-check + render |
| `day_of_week_iso(expr)` | `extract(isodow from expr)` | `(mod(extract(dayofweek from expr) + 5, 7) + 1)` | DuckDB's `isodow` is already ISO; BigQuery's `dayofweek` is Sun=1 and it has no `%` operator | `dim_date` ×2 |
| `month_start(expr)` | `cast(date_trunc('month', expr) as timestamp)` | `timestamp_trunc(expr, month)` | delegated to `timestamp_trunc_to(expr, 'month')` | ×4 |
| `month_number(expr)` | `extract(year …) * 100 + extract(month …)` | identical | EXTRACT is spelt the same; the dispatch is kept for one seam shape | ×4 |
| `seconds_between(a, b)` | `cast(date_diff('microsecond', a, b) as double) / 1000000.0` | `cast(timestamp_diff(b, a, microsecond) as float64) / 1000000.0` | BigQuery's DATE_DIFF takes DATEs, so it needs TIMESTAMP_DIFF, arguments reversed | ×2 |
| `safe_divide(n, d)` | `cast(n as double) / nullif(cast(d as double), 0)` | `safe_divide(n, d)` | BigQuery's SAFE_DIVIDE is NULL-on-zero and FLOAT64; the DuckDB branch reproduces both | ×3 |
| `regexp_contains(expr, pattern)` | `regexp_matches(expr, pattern)` | `regexp_contains(expr, pattern)` | same RE2 engine, different function name | no — self-check + render |
| `generate_surrogate_key(cols)` | `md5(concat_ws('\\|\\|', cols))` | `to_hex(md5(concat(cast(… as string), '\\|\\|', …)))` | BigQuery has no CONCAT_WS, its CONCAT takes only STRING, and MD5 returns BYTES | ×3 |

"called by a model" is counted with `grep -rhoE '\{\{ *[a-z_0-9]+\(' models/`. Nine of
the 26 dialect macros are not needed by this warehouse's SQL yet; they are exercised
two other ways instead, so none of them is untested code:

* `dbt run-operation polyglot_selfcheck --target duckdb` **executes** every DuckDB
  branch with constant inputs and compares value or `typeof()`, 44 cases, all `ok` —
  `make polyglot` runs it;
* `dbt run-operation polyglot_render --target bigquery` renders every BigQuery branch
  for inspection (rendering is not execution — see "What is NOT verified");
* `analyses/polyglot_showcase.sql` calls every macro inside real SQL and is compiled
  for both targets on every `dbt compile`.

### The decimal ceiling (BIGNUMERIC has no DuckDB equivalent)

BigQuery NUMERIC is 38,9 and BIGNUMERIC is 76.76 digits; DuckDB's DECIMAL is capped at
**38 digits total** and rejects anything wider (`Binder Error: DECIMAL type width must
be between 1 and 38`). The rule `decimal_type(p, s)` implements, and never deviates
from:

* `p <= 38` → DuckDB `decimal(p, s)`; BigQuery `numeric` if `s <= 9`, else `bignumeric`.
* `p > 38` → BigQuery `bignumeric`; on DuckDB a **compiler error**. It never silently
  renders `double`: a silent float is the failure mode the rule exists to prevent.

```
$ .venv/bin/dbt run-operation polyglot_render --args '{include_bignumeric: true}' --target bigquery
render decimal_type bigquery :: bignumeric
$ .venv/bin/dbt run-operation polyglot_render --args '{include_bignumeric: true}' --target duckdb
[error] [JinjaError (dbt1501)]: Failed to run operation invalid operation: Compilation Error:
decimal_type(77, 38): DuckDB DECIMAL is capped at 38 digits of precision (BigQuery would render
BIGNUMERIC, which has no DuckDB equivalent). Either declare a narrower decimal (p <= 38), or use
float_type() and accept 15-16 significant digits. Refusing to fall back to DOUBLE silently.
```

### The guardrail (`scripts/check_portability.py`, `make portability`)

"Portable" is an opinion until something counts it. The guardrail compiles **both**
targets into separate trees (`target/portability/<target>/`), strips SQL comments, and
scans every compiled `.sql` — models *and* the analysis — for the other engine's
dialect. It also checks that nothing under `models/` or `tests/` reads the target at
all (one allowlisted file, `models/staging/_thelook__sources.yml`, whose source
*database* name is the single genuinely target-dependent value).

* **15 BigQuery-only tokens** must not appear in the DuckDB render:
  `float64`, `safe_cast`, `safe_divide`, `generate_array`, `generate_date_array`,
  `regexp_contains`, `format_date`, `timestamp_trunc`, `timestamp_diff`, `bignumeric`,
  `struct(`, `* except (`, `array<`, `date_diff(` not followed by a quote,
  `bigquery-public-data`.
* **13 DuckDB-only tokens** must not appear in the BigQuery render:
  `try_cast`, `regexp_matches`, `strftime`, `generate_series`, `list_value`,
  `struct_pack`, `epoch_ms`, `* exclude (`, `bigint[]`, `::`, `date_trunc('`,
  `date_diff('`, `dev.thelook_ecommerce`.

Every token was measured against DuckDB 1.5.5: `int64` is *accepted* by DuckDB, so it
is deliberately not a DuckDB-direction token; `float64` is rejected, so it is.

```
$ make portability
compiled files checked: 30 (models: 29, analyses: 1)
BigQuery-only tokens in the DuckDB render: 0/15
DuckDB-only tokens in the BigQuery render: 0/13
target-branch findings: 0
PORTABLE
```

`--demo` proves it can fail: it writes `models/intermediate/_portability_demo.sql`
containing a raw `regexp_contains(...)` and a `{% if target.type == 'bigquery' %}`
branch, shows the guardrail reporting both, deletes the file in a `finally`, and
re-checks:

```
demo: wrote models/intermediate/_portability_demo.sql (raw regexp_contains + a target.type branch)
target/portability/duckdb/compiled/…/models/intermediate/_portability_demo.sql:3: token 'regexp_contains' -> select regexp_contains('a', 'a') as demo from "dev"."main"."stg_thelook__users"
models/intermediate/_portability_demo.sql:4: token 'target.type' -> {% if target.type == 'bigquery' %}limit 1{% endif %}
BigQuery-only tokens in the DuckDB render: 1/15
target-branch findings: 1
NOT PORTABLE: 2 finding(s)
demo: the guardrail failed as designed, then passed again
```

Independently of that demo, a raw leak was injected into a real model
(`safe_cast`, `timestamp_trunc`, `array<int64>`, `bignumeric`, `float64` in one model,
`strftime` in it too) and the guardrail reported 6 findings and exited 1 — 5/15
tokens in the DuckDB render and 1/13 in the BigQuery render — then went back to
`PORTABLE` once the file was removed.

### Where a macro could not hide the difference

Five things the seam had to work around, all of them measured here:

1. **The decimal ceiling.** BIGNUMERIC (76.76 digits) has no DuckDB equivalent, so
   `decimal_type(p>38)` refuses on DuckDB instead of pretending (above).
2. **The date series' element type.** BigQuery's `GENERATE_DATE_ARRAY` returns
   `ARRAY<DATE>`; DuckDB's `generate_series(date, date, interval)` needs an explicit
   interval *and* returns `TIMESTAMP[]`. The macro casts the result back to `date[]`,
   otherwise `dim_date.date_day` would be a TIMESTAMP on DuckDB and a DATE on BigQuery.
3. **`unnest(...)`'s alias in `FROM`.** This is the one place a *new* helper macro was
   needed rather than one more branch: BigQuery binds `unnest(arr) as date_day` to the
   **element**, DuckDB binds the same text to the **table** (giving a `STRUCT(unnest
   DATE)`), so DuckDB needs `as date_day__unnest(date_day)` — which BigQuery rejects.
   `unnest` itself stays plain SQL; only the alias is dispatched (`unnest_alias`).
4. **Division typing.** BigQuery's `SAFE_DIVIDE` returns FLOAT64, and DuckDB would keep
   `decimal / decimal` as DECIMAL, so `safe_divide` casts both sides to `double`. That
   is right for rates (and the self-check asserts `typeof` is `DOUBLE`), but it means
   the two money metrics that want *decimal* rounding —
   `mart_daily_revenue.average_order_value` and `mart_customer_summary.average_order_value`
   — keep `round(x / nullif(y, 0), 2)` cast to `money_type()` instead. That is a
   deliberate exception, not an oversight.
5. **The source database name.** `bigquery-public-data` vs `dev` is the one
   target-dependent value that belongs to a *relation*, not an expression, so it
   cannot live in a macro: it is one line in `models/staging/_thelook__sources.yml`,
   and the guardrail allowlists that file by name.

Three more differences *were* hideable but needed normalisation rather than a rename,
which is worth knowing before adding a macro:

* `FORMAT_DATE` takes the **format first** on BigQuery, `STRFTIME` the **value first**;
* BigQuery's bare `WEEK` starts on Sunday where DuckDB's `'week'` is ISO, so
  `timestamp_trunc_to(…, 'week')` renders `week(monday)` on BigQuery;
* BigQuery's `DAYOFWEEK` numbers Sunday 1 and has no `%` operator, so
  `day_of_week_iso` renders `(mod(extract(dayofweek from …) + 5, 7) + 1)`.

One caveat is documented in `arrays.sql` rather than solved:
`generate_date_series(…, '1 month')` drifts on DuckDB when it starts on a month end
(DuckDB adds the interval to the previous element: `2024-01-31 → 02-29 → 03-29`).
BigQuery's behaviour in that case is not measurable here. Start month steps on the 1st.

## The DuckDB fixture

**Why it exists:** there are no Google credentials on this machine, so the real
dataset cannot be read from here. The fixture lets the complete model tree run and
be tested locally, unchanged.

**What it is:** `scripts/fixtures/thelook_ecommerce.sql` generates the 7 tables in
`dev.duckdb`, schema `thelook_ecommerce`. It copies the real tables' column names, column
order and types (TIMESTAMP is loaded as `timestamptz`, as the `bigquery` extension
would deliver it) and the value vocabularies the tests assert. **The rows are
invented.** They are deterministic (hash-based) and coherent: every foreign key
resolves, `num_of_item` equals the item count, lifecycle timestamps are ordered, and
each order item consumes its own inventory unit. They are not a sample of the real
data. Their volumes, distributions and every number measured on them say nothing
about `bigquery-public-data`.

| table | fixture rows |
|---|---|
| distribution_centers | 10 |
| products | 200 |
| users | 400 |
| inventory_items | 10000 (8000 sold, 2000 open) |
| orders | 3000 |
| order_items | 8000 |
| events | 20000 |

`scripts/load_duckdb_sources.sh` (`make fixtures`) recreates the tables on every
run, prints the counts, and runs 24 integrity/coherence checks. If any check finds
a violating row, it exits 1.

## The two targets

| target     | engine                | data lives in        | credentials                        | state here |
|------------|-----------------------|----------------------|------------------------------------|------------|
| `duckdb`   | DuckDB 1.5.5 via ADBC | `dev.duckdb` (local) | none                               | **runs green on the fixture** |
| `bigquery` | BigQuery (GCP)        | GCP project; reads `bigquery-public-data` | Google ADC or a service-account key | **compiles; never connected** |

### `duckdb`

```
type: duckdb
path: dev.duckdb        # gitignored; `make clean` deletes it
extensions: [httpfs, iceberg, bigquery]
```

Three extensions are declared, and two of them are only loadable because of a
prerequisite that is easy to miss:

* `httpfs`, `iceberg` come from the **core** extension repository and load
  directly.
* `bigquery` is a **community** extension. dbt-oss 2.0.5 cannot express that in
  `profiles.yml` — see "Known dbt v2 findings" below — so it is installed into
  DuckDB's extension cache once, by `scripts/install_prereqs.sh`, and the plain
  name then loads that cached community build.

### `bigquery`

```
type: bigquery
method: oauth                       # gcloud application-default credentials
database: coreychimpbot             # the GCP project (v2 calls it database)
schema: experiments_<DBT_ENV>       # dataset prefix per environment; DBT_ENV=dev by default
location: US
maximum_bytes_billed: 1 GB          # hard cost ceiling, override with BQ_MAXIMUM_BYTES_BILLED
```

`maximum_bytes_billed` is a real ceiling, not a convention: a query that would
bill more than the configured number of bytes **fails instead of running**. The
default is 1 GB so that no accidental query in this repository can be expensive.
How many bytes a full build over the real `thelook_ecommerce` tables would scan
has not been measured. If it is over the ceiling, the build fails rather than bills.

This target has **never been connected**. `make bq` checks for credentials first
and exits 2 with an explanation rather than surfacing a driver authentication
error.

To make the leg real, pick one:

```bash
gcloud auth application-default login \
  --scopes=https://www.googleapis.com/auth/bigquery,https://www.googleapis.com/auth/cloud-platform
```

or use a service-account key file and change the output to
`method: service-account` with `keyfile: <path>` (dbt v2 supports
service-account, gcloud OAuth, and Entra workload identity federation).

## Pinned versions

| thing | pin | where it is pinned |
|---|---|---|
| dbt | `dbt-oss 2.0.5` (dbt v2, Fusion engine, Apache-2.0 build) | `pyproject.toml` + `uv.lock` |
| DuckDB engine | `1.5.5` | `dbc install duckdb` — the dbc-installed ADBC driver is DuckDB 1.5.5 |
| DuckDB CLI | `1.5.5` (`v1.5.5 (Variegata) d8cdaa33fd`) | `scripts/install_prereqs.sh`, sha256-verified |
| dbc | `0.3.0` | `scripts/install_prereqs.sh`, sha256-verified |
| community `bigquery` extension | build `27d85ad` (`installed_from = community`) | installed by `scripts/install_prereqs.sh`; the community repo publishes a single build, so there is no semver to pin |

`scripts/check_env.sh` asserts the dbt, dbc, driver, DuckDB and extension pins and
exits 1 listing every gap. The binaries can be overridden (`DBT_BIN`, `DBC_BIN`,
`DUCKDB_BIN`), which is how the failing path is demonstrated without uninstalling
anything.

## Prerequisites

```bash
make setup          # uv sync + scripts/install_prereqs.sh
make check-env      # assert everything, loudly
```

`uv sync` installs dbt v2 from `pyproject.toml`. `scripts/install_prereqs.sh`
installs what pip cannot: `dbc`, the DuckDB ADBC driver (`dbc install duckdb`),
the DuckDB CLI, and the community `bigquery` extension. It downloads from the
official release URLs, verifies a sha256, and installs into `~/.local/bin`
(`PREFIX=` overrides), so it needs no sudo.

## Running

```bash
make duck         # check-env, load the fixture, then dbt build --target duckdb
make fixtures     # (re)load the DuckDB fixture only
make bq           # dbt build --target bigquery (exits 2 without credentials)
make build-both   # duck, then bq
make parity       # every model on both targets: rows, column names, canonical column
                  # types, per-column checksums; writes parity-report.md/.json and exits
                  # non-zero on a real mismatch (see "What is NOT verified")
make polyglot     # the macro layer end to end: 44 self-check cases on DuckDB, the renders
                  # for both targets, the decimal ceiling, then the guardrail and its --demo
make portability  # just the guardrail: compile both targets, scan each render for the other
                  # dialect, fail on a target branch in a model
```

To query a mart after `make duck`, from the repo root. This is the form used for
every `dbt show` below. The Makefile exports `DBT_PROFILES_DIR`, so if a direct
call cannot find the profile, set `DBT_PROFILES_DIR` to the repo root:

```bash
.venv/bin/dbt show --target duckdb --limit 5 \
  --inline "select * from {{ ref('mart_product_performance') }}"
```

`make duck`, verbatim excerpts. The run also prints the 7 `check-env` lines, the
fixture's 24 `ok` checks and 197 `Succeeded`/`Passed` lines:

```
Row counts:
  distribution_centers       10
  products                  200
  users                     400
  inventory_items         10000
  orders                   3000
  order_items              8000
  events                  20000
...
Fixture loaded and coherent.
.../.venv/bin/dbt build --target duckdb
   dbt-oss 2.0.5
...
 Succeeded model main.fct_orders (table) [157 of 197 in 0.21s]
...
==================== Execution Summary =====================
Finished 'build' successfully for target 'duckdb' [5.5s]
Processed: 29 models | 168 tests
Summary: 197 total | 197 success
```

The build now has no warnings: the two skeleton-era warnings (unused layer
configuration paths and "nothing to do") disappeared once each layer had models.

## What is verified

Measured on this machine on 2026-09-26, dbt-oss 2.0.5 / DuckDB 1.5.5 / dbc 0.3.0.

**The model tree, on DuckDB, on the fixture:**

* `make duck` exits 0 twice in a row: `Processed: 29 models | 168 tests`,
  `Summary: 197 total | 197 success` both times ([5.5s] on the second run). The
  fixture is reloaded from scratch each time, so the second run shows the whole
  pipeline is idempotent.
* `dbt ls --resource-type model --target duckdb --quiet | wc -l` → `29`: 7 staging,
  11 intermediate and 11 marts (card 3 added the eleventh, `dim_date`).
* The 168 tests are 165 generic tests plus 3 singular tests. The SPEC's 10 cross-mart
  `relationships` tests all exist and pass:
  `fct_orders.user_id → dim_users`,
  `fct_order_items.{order_id → fct_orders, user_id → dim_users, product_id → dim_products,
  distribution_center_id → dim_distribution_centers}`,
  `fct_inventory_items.{product_id → dim_products, distribution_center_id → dim_distribution_centers}`,
  `dim_products.distribution_center_id → dim_distribution_centers`,
  `mart_product_performance.product_id → dim_products`,
  `mart_customer_summary.user_id → dim_users`. There is one extra:
  `fct_order_items.inventory_item_id → fct_inventory_items`.
* Mart grains, measured with `dbt show` (every key is distinct):

  | mart | rows |
  |---|---|
  | fct_orders | 3000 |
  | fct_order_items | 8000 |
  | fct_inventory_items | 10000 |
  | dim_users | 400 |
  | dim_products | 200 |
  | dim_distribution_centers | 10 |
  | dim_date | 1415 |
  | mart_daily_revenue | 1040 |
  | mart_product_performance | 200 |
  | mart_customer_summary | 400 |
  | mart_cohort_retention | 864 |

  `dim_date`'s 1415 rows are the fixture's order window (2022-02-16 to 2025-12-31),
  checked by a query, not by eye: `count(*) = date_diff('day', min(date_day),
  max(date_day)) + 1`, no duplicate dates, `day_of_week_iso` equals DuckDB's own
  `isodow` on every row, `is_weekend` equals `day_of_week_iso >= 6` on every row,
  `date_month`/`month_start_at`/`days_since_first_order`/`year_number`/`month_of_year`/
  `day_of_month` all match a recomputed expression, 404 rows are weekend days, and no
  `mart_daily_revenue.revenue_date` is missing from the spine.

* Gross revenue reconciles to the cent across layers:
  `sum(stg_thelook__order_items.sale_price)` and the totals of `fct_orders`,
  `fct_order_items`, `mart_daily_revenue`, `mart_product_performance`,
  `mart_customer_summary` and `mart_cohort_retention` are all `642483.63`. Every
  cohort's month-0 `retention_rate` is exactly 1.0.
* Sample output, `dbt show` on `mart_product_performance` (top 3 by gross revenue).
  Remember that these products and numbers are invented fixture data:

  ```
  │ product_id ┆ product_name                         ┆ brand        ┆ units_sold ┆ gross_revenue ┆ gross_margin ┆ gm_rate ┆ return_rate │
  │ 64         ┆ Lucky Brand Women's Classic Pants    ┆ Lucky Brand  ┆ 57         ┆ 8572.8        ┆ 3919.89      ┆ 0.4572  ┆ 0.1053      │
  │ 170        ┆ Calvin Klein Women's Essential Pants ┆ Calvin Klein ┆ 50         ┆ 7467.         ┆ 4062.        ┆ 0.544   ┆ 0.16        │
  │ 21         ┆ Volcom Women's Everyday Dresses      ┆ Volcom       ┆ 50         ┆ 7145.5        ┆ 3090.5       ┆ 0.4325  ┆ 0.06        │
  ```

* Staging timestamps are naive UTC whatever the session time zone (measured with
  the session set to `America/Los_Angeles`, 0 mismatches). See NOTES.md.

**The macro layer, card 3 (all on this machine, dbt-oss 2.0.5 / DuckDB 1.5.5):**

* `dbt run-operation polyglot_selfcheck --target duckdb` → exit 0,
  `selfcheck: all 44 cases ok on duckdb`. Every DuckDB branch of every macro is
  **executed** with constant inputs and compared to its expected value or `typeof()`:
  `safe_cast` NULL-on-failure and `BIGINT`, `safe_divide` NULL on a zero divisor and
  `DOUBLE`, `date_diff_days` sign and magnitude, the three `day_of_week_iso` cases
  (Mon 1 / Fri 5 / Sun 7), `timestamp_trunc_to` hour/week/quarter, `format_month`,
  `month_start`, `month_number`, `seconds_between`, `to_utc_timestamp` with a
  `+02` input, the three generators, `generate_surrogate_key`,
  `except_columns` (by returned column names, since it is not an expression),
  `struct_literal` (by field access) and the type macros incl. `DECIMAL(38,9)`.
* `dbt run-operation polyglot_render --target bigquery` → exit 0, 31 renderings, e.g.
  `render safe_cast bigquery :: safe_cast('42' as int64)`,
  `render format_month bigquery :: format_date('%Y-%m', date_day)`,
  `render day_of_week_iso bigquery :: (mod(extract(dayofweek from date_day) + 5, 7) + 1)`,
  `render timestamp_trunc_to bigquery :: timestamp_trunc(created_at, week(monday))`,
  `render safe_divide bigquery :: safe_divide(gross_margin, gross_revenue)`.
* The decimal ceiling: the same command with `include_bignumeric` prints
  `bignumeric` on `--target bigquery` and **fails** on `--target duckdb` with the
  ceiling message (full text above). `make polyglot` asserts both halves.
* `make portability` → `PORTABLE`: 30 compiled files (29 models + the analysis),
  0/15 BigQuery-only tokens in the DuckDB render, 0/13 DuckDB-only tokens in the
  BigQuery render, 0 target-branch findings.
* `python3 scripts/check_portability.py --demo` → exit 0: reports 1 dialect finding
  and 1 target-branch finding in its injected demo model and `NOT PORTABLE: 2
  finding(s)`, deletes the file, then reports `PORTABLE` again. Separately, a raw leak
  injected into a real model by hand (5 BigQuery-only + 1 DuckDB-only token) exited 1
  with 6 findings and went back to `PORTABLE` when removed.
* `make polyglot` → exit 0, `polyglot check: all steps ok` (its 7 steps: check-env,
  fixtures, self-check, both renders, the ceiling, the guardrail, the guardrail's
  `--demo`).
* The refactor that moved the seam into `macros/polyglot/` did not move any number:
  the three rates rewritten to `safe_divide` equal the old
  `cast(x as float) / nullif(y, 0)` formula row for row, all mart row counts are
  unchanged, and gross revenue is still `642483.63`.

**The BigQuery target, without executing anything:**

* `dbt compile --target bigquery` → exit 0:
  `Finished 'compile' successfully for target 'bigquery'`,
  `Processed: 29 models | 168 tests | 1 analysis`. The rendered SQL uses the BigQuery
  branches: `numeric`, `float64`, `int64`, `timestamp_trunc(..., month)`,
  `timestamp_trunc(..., week(monday))`, `timestamp_diff(..., microsecond)`,
  `safe_divide(...)`, `safe_cast(... as int64)`, `date_diff(..., ..., day)`,
  `generate_date_array(..., interval 1 day)`, `struct(1 as a, 2 as b)`,
  `* except (a, b)`, `array<int64>`, `format_date('%Y-%m', ...)`,
  `(mod(extract(dayofweek from ...) + 5, 7) + 1)` and
  `to_hex(md5(concat(cast(... as string), '||', ...)))`. Every source reference
  resolves to `bigquery-public-data`.`thelook_ecommerce` — and the guardrail asserts
  that no DuckDB-only token and no `dev.thelook_ecommerce` leaks into that render.
* `dbt parse --target bigquery` → exit 0.

**From card 1 (the plumbing), still true:**

* `dbt debug --target duckdb` → `Debugged All checks passed!` with `connection
  test: OK`, echoing the resolved connection (`path: dev.duckdb`, `schema: main`,
  `extensions: [httpfs, iceberg, bigquery]`).
* `dbt debug --target bigquery` → the BigQuery adapter **resolves the profile and
  echoes it**, including `"maximum_bytes_billed": 1000000000`, then fails only the
  connection test: `AuthenticationFailed (dbt1011) ... could not find default
  credentials`.
* `scripts/check_env.sh` → exit 0 with everything installed. Exit 1 with one named
  `FAIL` line for each of: DuckDB absent (`DUCKDB_BIN=/nonexistent/duckdb`), dbc
  absent (`DBC_BIN=/nonexistent/dbc`), and the ADBC driver absent (measured by
  moving `~/.config/adbc` aside), each naming the fix.
* `scripts/install_prereqs.sh` → exercised from scratch into an empty `PREFIX`
  with `dbc` and `duckdb` removed from `PATH`: it downloaded both release assets,
  verified their sha256, installed them, and exited 0.
* The extensions really are loading: removing the DuckDB `bigquery` build from
  DuckDB's extension cache makes `dbt build`/`dbt show` fail with
  `HTTP Error: Failed to download extension "bigquery" ... (HTTP 404)`, and
  installing it back with `INSTALL bigquery FROM community` makes it pass again.
* `scripts/parity.py` (card 4) was run end to end on 2026-09-27 against a real
  BigQuery service account and measured **all 29 models on both targets**, not just
  row counts: column names, canonical column types, and a per-column
  order-independent checksum plus a null count and a distinct count. `make parity`
  writes `parity-report.md` and `parity-report.json`. Two things it verifies about
  *itself* before it measures anything: the digest self-check (both engines hash a
  fixture of constants to the same numbers) and the DuckDB-vs-DuckDB baseline
  (`dev.duckdb` is rebuilt from scratch and every measurement has to reproduce).
  Both pass. The run exits 1, on one real mismatch it found —
  `mart_product_performance.gross_margin_rate` is `DOUBLE` on DuckDB and `NUMERIC`
  on BigQuery — see "What is NOT verified".

## What is NOT verified

* **The BigQuery target has been *measured read-only*, and has still never been
  *materialised*.** There was no Google credential on this machine when the earlier
  cards were written; there is one now (a service-account key file, used through the
  same `BQ_KEYFILE` variable the profile reads), and card 4 exercised it. What that
  proves: the compiled SQL for all 29 models really does execute on BigQuery and
  returns the real `bigquery-public-data.thelook_ecommerce` rows, so every
  `bigquery__` macro branch in the model tree is now *executed*, not merely
  inspected, and the column names and canonical types line up. What it does not
  prove: `dbt build --target bigquery` still fails, with
  `Access Denied: Project coreychimpbot: User does not have bigquery.datasets.create
  permission in project coreychimpbot`. The target dataset `coreychimpbot.experiments_dev`
  does not exist, the project has no other dataset the account could write to, and
  the account may not create one, so no model has ever been *materialised* in
  BigQuery and `make bq` still exits non-zero. Enforcement of `maximum_bytes_billed`
  is also still unconfirmed (the harness sets it per query and no query hit it).
* **The macro layer's BigQuery side has now been *run*, but only inside the model
  tree.** `polyglot_render --target bigquery` and the guardrail consume rendered
  text, so as *tools* they still only inspect: a rendering that looks right but is
  rejected by BigQuery could pass them. Card 4 narrowed that gap a lot — the whole
  model tree now executes on BigQuery read-only, so every `bigquery__` branch the
  models actually call has been accepted by the engine — but a macro used only in
  an analysis, and not in any model, still would not be. The specific models named
  before are now exercised: `dim_date` is the first to call
  `generate_date_series`, `day_of_week_iso`, `format_date_str`, `date_diff_days` and
  `unnest_alias`, and it runs on BigQuery.
* **The guardrail is a blacklist, not a proof.** It fails on the 15 BigQuery-only and
  13 DuckDB-only tokens listed above. A BigQuery-only construct that is not on the
  list (or a dialect difference expressed in a way the token list does not spell)
  would pass silently, and the DuckDB-side compile proves only that the *DuckDB*
  render is valid there. What it does prove is exactly what the card asked for: no
  `target.type` branch in any model or test, no `bigquery-public-data` in the DuckDB
  render, and no `dev.thelook_ecommerce` in the BigQuery render.
* **`polyglot_selfcheck` only runs on DuckDB.** On `--target bigquery` it prints
  `selfcheck skipped: bigquery cannot be executed here (no credentials; render-only)`
  and exits 0 rather than pretending; `make polyglot` runs the DuckDB half only.
* **The real dataset's row counts are now measured, its *contents* are not.**
  Card 4's harness read every model's real rows through BigQuery and reports
  counts and checksums for them (`parity-report.json`). The real tables are:
  orders 124,952 · order_items 181,313 · users 100,000 · products 29,120 ·
  inventory_items 489,625 · events 2,425,698 · distribution_centers 10. Every
  *test result* and every revenue figure quoted in this README, though, still
  comes from the **generated fixture**: invented rows with the real schema. The
  tests have never been run against the real data, so these assumptions remain
  unverified (details in NOTES.md):
  * the real row counts and value distributions;
  * that real `events.user_id` is never null. SPEC requires `not_null` on it, but
    anonymous sessions probably have none, so this test may fail on BigQuery;
  * that real `events.traffic_source` uses the users vocabulary (Search, Organic,
    Facebook, Email, Display). It may not, and the `accepted_values` test would fail;
  * that each real order item consumes its own inventory unit, which the fixture
    assumes (`fct_order_items.inventory_item_id` has a `unique` test);
  * that real prices have at most 2 decimal places. The `decimal(18,2)`/`numeric`
    cast rounds anything finer;
  * that every real order has at least one item and that `num_of_item` matches, as
    the singular test asserts.
* **Parity is not established, but it is now *measured* rather than assumed.**
  `make parity` compares all 29 models on both targets and separates the two kinds of
  difference that exist today:

  * **A real defect it found.** `mart_product_performance.gross_margin_rate` is
    `DOUBLE` on DuckDB and `NUMERIC` on BigQuery. `bigquery__safe_divide` renders
    BigQuery's `SAFE_DIVIDE` on the column's own type, and `SAFE_DIVIDE` returns the
    input type, so on two `NUMERIC` inputs it returns `NUMERIC` while the DuckDB
    branch casts to `DOUBLE`. The macro's own docstring says it is float-typed on
    purpose, so the BigQuery branch is not doing what it says. This is what makes
    the run exit 1. `int_products__returns.return_rate` and
    `mart_cohort_retention.retention_rate` call the same macro but are safe: their
    inputs are integers, so `SAFE_DIVIDE` yields `FLOAT64` and the two types agree.
  * **Different source data.** 28 of the 29 models differ on row counts and
    checksums, because the DuckDB leg reads the fixture and the BigQuery leg reads
    the real dataset — 3,000 fixture orders against 124,952 real ones, 20,000
    fixture events against 2,425,698 real ones, and so on. Those checksums are
    reported, not gated, until both legs read one dataset; `--same-data` promotes
    them to gating for that day.

  One model matches on *everything*, values included:
  `stg_thelook__distribution_centers`. The fixture copies the real ten distribution
  centres verbatim, and the checksums agree — the proof that this comparison is
  comparing data and not just always answering "differs".
  Meaningful value parity needs both legs reading the same data (cards 5/6). One way
  is to point the DuckDB leg at the real tables through the `bigquery` extension,
  which needs credentials.
* **Surrogate keys have now run on both sides but still do not *match*.** Both
  branches hash the same `'||'`-joined integer text by construction, and the
  BigQuery side executed for the first time in card 4 (read-only, whole model
  tree). The parity harness compares the key columns like any other column; they
  differ exactly where the underlying rows differ, and nowhere else.
* **The singular tests' failing path has not been exercised.** All three return zero
  rows on the fixture. No fixture with an injected violation has been run through
  them.
* **The fallback path (a separate project for whatever cannot be transpiled) does
  not exist here.** It is card 7's job; this project is deliberately one tree.

## Known dbt v2 findings

Recorded so the next card does not have to re-derive them. All measured with
dbt-oss 2.0.5 unless stated otherwise.

1. **`extensions:` in `profiles.yml` rejects the documented name/repo pair.**
   The name/repo form documented for community extensions —

   ```yaml
   extensions:
     - name: bigquery
       repo: community
   ```

   fails with `InvalidConfig (dbt1005): Configuration Error: extensions: item 2
   must be a string, got Mapping {name, repo}`. Only plain strings are accepted.
   (The documentation for this form appears to follow the Python `dbt-duckdb`
   adapter; it is not the v2 profile schema.)
2. **`"bigquery:community"` is not an alternative.** It is concatenated into one
   extension name and 404s: `Failed to download extension "bigquerycommunity"` .
3. **A bare name is only looked up in the CORE repository.** With the community
   build absent from the cache, `bigquery` 404s against
   `extensions.duckdb.org`. Hence the out-of-band
   `INSTALL bigquery FROM community` in `scripts/install_prereqs.sh`.
4. **dbt v2's bundled DuckDB driver *can* process extensions**, so the widely
   repeated claim that it "cannot load extensions" did not reproduce here: with
   the dbc driver hidden, the bundled driver still ran the extension `INSTALL`
   statements and successfully loaded `httpfs` and `iceberg` from the core repo.
   What the bundled driver *does* change is the **engine version**: it carries
   DuckDB **1.5.4** instead of the pinned 1.5.5, silently. That version drift is
   the reason `dbc install duckdb` is a hard prerequisite in `check_env.sh`.
5. **`dbt parse` does not validate profile fields.** A junk key added to the
   bigquery output parses cleanly, so a green `dbt parse --target bigquery` says
   only that the profile renders. `dbt debug` is the command that reports on the
   fields the adapter actually read.
6. **`maximum_bytes_billed` is accepted by the v2 BigQuery adapter** and resolves
   to an integer (visible in `dbt debug --target bigquery`'s echo of the resolved
   connection). Whether the real API enforces it is untested here.
7. **`profiles.yml` does not need to live in `~/.dbt`.** `DBT_PROFILES_DIR` is
   exported by the Makefile, so the committed copy is the one in use.
8. **Generic test arguments must be nested under `arguments:`.** Write
   `relationships: {arguments: {to: ref('x'), field: y}}` and
   `accepted_values: {arguments: {values: [...]}}`. The flat v1 form (`to:`/`field:`/`values:`
   directly under the test) is a build-breaking `DbtYamlValidationError dbt1159`
   (recorded in SPEC.md section 0). Every generic test in this project uses the
   nested form under `data_tests:`.
9. **Singular tests need no declaration.** A `.sql` file under `test-paths`
   (`tests/`) containing one `select` is picked up automatically, with no YAML entry
   and no config block. It is named after the file (`Passed test
   assert_no_orphan_order_items`), and its `ref()`s place it in the DAG. For example,
   in the second `make duck` run `assert_timestamps_are_before_after` (which refs only
   staging) ran as node 42 of 187, long before the marts. `assert_order_item_count_matches_orders`
   also refs `fct_orders`, so it ran as node 183, after `fct_orders` (node 144). It
   passes when it returns zero rows. One side effect: `--select path:models/marts`
   also selects that singular test, presumably through indirect test selection (64 tests
   listed, of which 63 are the marts' generic tests).
10. **`dbt ls` writes its banner and summary to stdout.**
    `dbt ls --resource-type model --target duckdb | wc -l` prints `36` for 28
    models: the 28 node lines plus the `dbt-oss 2.0.5` / `Loading profiles.yml` /
    package-resolution banner, a `Selected nodes` header and the execution summary.
    Add `--quiet` to get only the nodes (`28`).
11. **`dbt show --inline` appends its own `limit`.** An inline query that already
    ends in `limit N` fails with
    `Parser Error: syntax error at or near "limit"`. Use `--limit N` instead.
