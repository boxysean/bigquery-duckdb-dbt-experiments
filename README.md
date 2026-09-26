# bigquery-duckdb-dbt-experiments

One dbt v2 project, two targets. The same models are built against **BigQuery**
and against a local **DuckDB** file, with the dialect differences pushed into
`macros/` rather than into a forked model tree. Sean's framing: *"one single
project power both with using macros to help transpile."*

**Status: a 28-model warehouse over `thelook_ecommerce`, built and tested on
DuckDB only.** The model tree is the one described in `SPEC.md`: 7 staging views,
11 intermediate views and 10 mart tables over the 7 tables of Google's public
`bigquery-public-data.thelook_ecommerce` dataset. On the `duckdb` target the whole
tree builds and 159 tests pass, twice in a row. That run reads a **generated
fixture**: invented data with the real schema, not the real dataset (see "The
DuckDB fixture"). On the `bigquery` target the project compiles and parses. **It
has never run there:** this machine has no Google credentials.

## Layout

```
dbt_project.yml         dbt v2 project (no config-version; v2 does not use it)
profiles.yml            BOTH targets, committed — it holds no credentials
packages.yml            empty on purpose: every package must work on both targets
pyproject.toml + uv.lock  dbt itself, pinned (dbt-oss 2.0.5)
Makefile                make setup | check-env | fixtures | duck | bq | build-both | parity | clean
models/staging/         7 views: rename + cast only, one per source table; the source definition
models/intermediate/    11 views: the joins and aggregates
models/marts/           10 tables: fct_*, dim_*, mart_*
macros/cross_target.sql the transpile seam: adapter-dispatch macros
tests/                  3 singular tests (cross-model invariants)
scripts/check_env.sh    prerequisite gate; fails loudly, never half-succeeds
scripts/install_prereqs.sh  dbc, the DuckDB driver, the DuckDB CLI, the community extension
scripts/load_duckdb_sources.sh  loads the DuckDB fixture and checks its integrity (make fixtures)
scripts/fixtures/       the fixture generator SQL, plus the grain/coherence check queries
scripts/run_bq.sh       the BigQuery leg: refuses clearly when credentials are absent
scripts/parity.sh       row-count comparison across both targets
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
(types, time zones, month truncation, date diffs, surrogate-key hashing) is a
dispatched macro in `macros/cross_target.sql`.

| layer | models | materialised | what it does |
|---|---|---|---|
| staging | `stg_thelook__{orders,order_items,users,products,inventory_items,distribution_centers,events}` | view | rename (`id` → `<entity>_id`) and cast; no joins |
| intermediate | `int_order_items__enriched`, `int_orders__item_rollup`, `int_orders__daily`, `int_users__lifetime_orders`, `int_users__first_order_cohort`, `int_cohorts__user_months`, `int_products__sales`, `int_products__returns`, `int_inventory_items__enriched`, `int_inventory__by_product_center`, `int_events__sessions` | view | joins and aggregates; grain stated per model |
| marts | `fct_orders`, `fct_order_items`, `fct_inventory_items`, `dim_users`, `dim_products`, `dim_distribution_centers`, `mart_daily_revenue`, `mart_product_performance`, `mart_customer_summary`, `mart_cohort_retention` | table | facts, dimensions and aggregates |

Conventions, all stated in the model docs:

* Money is `money_type()`: `decimal(18,2)` on DuckDB, `numeric` on BigQuery. The currency is **USD**.
* Rates are `float_type()` (`double` / `float64`).
* Every `*_at` column is a **naive UTC timestamp**. BigQuery TIMESTAMP arrives in DuckDB
  as TIMESTAMPTZ, and a plain cast would apply the session time zone.
* "Gross" means every order item, whatever its status. Returns are separate columns.
* Surrogate keys are used only where the grain has no natural key: user × month,
  product × center, and cohort × activity month.

Every model and every column has a description. The tests are 156 generic tests
(`unique`/`not_null` on every key, `not_null` on every foreign key, `relationships`
across the marts, `accepted_values` on status/gender/traffic_source/event_type/department)
and 3 singular tests.

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
make parity       # row counts per mart model, both targets (see "What is NOT verified")
```

To query a mart after `make duck`, from the repo root. This is the form used for
every `dbt show` below. The Makefile exports `DBT_PROFILES_DIR`, so if a direct
call cannot find the profile, set `DBT_PROFILES_DIR` to the repo root:

```bash
.venv/bin/dbt show --target duckdb --limit 5 \
  --inline "select * from {{ ref('mart_product_performance') }}"
```

`make duck`, verbatim excerpts. The run also prints the 7 `check-env` lines, the
fixture's 24 `ok` checks and 187 `Succeeded`/`Passed` lines:

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
 Succeeded model main.fct_orders (table) [144 of 187 in 0.49s]
...
==================== Execution Summary =====================
Finished 'build' successfully for target 'duckdb' [5.8s]
Processed: 28 models | 159 tests
Summary: 187 total | 187 success
```

The build now has no warnings: the two skeleton-era warnings (unused layer
configuration paths and "nothing to do") disappeared once each layer had models.

## What is verified

Measured on this machine on 2026-09-26, dbt-oss 2.0.5 / DuckDB 1.5.5 / dbc 0.3.0.

**The model tree, on DuckDB, on the fixture:**

* `make duck` exits 0 twice in a row: `Processed: 28 models | 159 tests`,
  `Summary: 187 total | 187 success` both times ([5.8s] on the second run). The
  fixture is reloaded from scratch each time, so the second run shows the whole
  pipeline is idempotent.
* `dbt ls --resource-type model --target duckdb --quiet | wc -l` → `28`: 7 staging,
  11 intermediate and 10 marts.
* The 159 tests are 40 staging, 53 intermediate and 63 mart generic tests, plus 3
  singular tests. The SPEC's 10 cross-mart `relationships` tests all exist and pass:
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
  | mart_daily_revenue | 1040 |
  | mart_product_performance | 200 |
  | mart_customer_summary | 400 |
  | mart_cohort_retention | 864 |

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

**The BigQuery target, without executing anything:**

* `dbt compile --target bigquery` → exit 0:
  `Finished 'compile' successfully for target 'bigquery'`,
  `Processed: 28 models | 159 tests`. The rendered SQL uses the BigQuery branches:
  `numeric`, `float64`, `timestamp_trunc(..., month)`, `timestamp_diff(..., microsecond)`,
  and `to_hex(md5(concat(cast(... as string), '||', ...)))`. Every source reference
  resolves to `bigquery-public-data`.`thelook_ecommerce`.
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
* `scripts/parity.sh` was exercised end to end on a throwaway one-row mart in
  card 1 (exit 2, BigQuery leg unavailable). That is not evidence of parity.

## What is NOT verified

* **Nothing has ever run on BigQuery.** There are no credentials. `dbt compile`
  and `dbt parse --target bigquery` render Jinja into SQL text. They do not send it
  to BigQuery, so they do not show that the SQL is valid BigQuery, that the types
  line up, or that a single row comes back. Every `bigquery__` macro branch is
  unexecuted. The project, dataset and location in the profile are unconfirmed, and
  so is enforcement of `maximum_bytes_billed`.
* **Nothing has been measured on the real dataset.** Every row count, revenue figure
  and test result above comes from the **generated fixture**: invented rows with the
  real schema. Unverified assumptions about the real data (details in NOTES.md):
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
* **Parity is not established, and `make parity` cannot establish it as the
  project stands.** It compares row counts per mart across targets, but the DuckDB
  leg reads the fixture and the BigQuery leg would read the real dataset, so the
  counts are expected to differ. `bash scripts/parity.sh` was run and exits 2: it
  prints the ten marts' DuckDB row counts (3000, 8000, 10000, 400, 200, 10, 1040,
  200, 400, 864), prints `n/a` for every BigQuery count, and ends with
  `the bigquery leg could not be measured: no Google credentials on this machine`.
  The BigQuery leg never executes a query: the adapter fails to authenticate first.
  Meaningful parity needs both legs reading the same data. One way is to point the
  DuckDB leg at the real tables through the `bigquery` extension, which needs
  credentials.
* **Surrogate keys are not shown to match across targets.** Both branches hash the
  same `'||'`-joined integer text by construction, but the BigQuery side has never run.
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
