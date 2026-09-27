# SPEC — the ~30-model thelook_ecommerce warehouse (card t_d0cac5da)

This file is the design contract for the model tree. It is written by the orchestrator
(Bruno) and is authoritative: **implement what it says; if something in it is wrong or
impossible, stop and say so in `NOTES.md` rather than silently doing something else.**

Do not commit anything. Do not touch `main`. Do not edit `profiles.yml` or `dbt_project.yml`
(except where a phase explicitly says to).

---

## 0. Environment facts (measured on this machine, 2026-09-26)

* dbt is **dbt-oss 2.0.5** (dbt v2, Fusion engine). It is at `.venv/bin/dbt`;
  `DBT_PROFILES_DIR` must be the repo root (the Makefile exports it).
* `make check-env` asserts the prerequisites and passes. `make duck` = `dbt build --target duckdb`.
* Generic tests in dbt v2 **must** use the new argument nesting. This exact form is verified:

  ```yaml
  - name: order_id
    data_tests:
      - unique
      - not_null
      - relationships:
          arguments:
            to: ref('fct_orders')
            field: order_id
      - accepted_values:
          arguments:
            values: ['Complete', 'Shipped']
  ```

  The flat form (`to:`/`field:`/`values:` at top level) is a **build-breaking error**
  (`DbtYamlValidationError dbt1159`). `data_tests:` is accepted (the old `tests:` key is
  also fine, but use `data_tests:`).
* `dbt lint` needs the full dbt distribution and is **not available** here. Do not call it.
* `dbt build`, `dbt test`, `dbt ls`, `dbt show`, `dbt run`, `dbt seed`, `dbt parse`,
  `dbt compile`, `dbt run-operation` all exist in v2.
* On the DuckDB target, `target.database` is `dev` (the `dev.duckdb` file stem) and
  `target.schema` is `main`. Verified: `select current_database()` → `dev`.
* There are **no Google credentials** on this machine. Never run anything against the
  BigQuery target beyond `dbt parse --target bigquery`. Never fake a BigQuery run.
* `packages.yml` is deliberately empty: **no dbt packages**. No `dbt_utils`. Anything you
  need, write as a macro in `macros/`.

## 1. Source data — one source definition, two targets

The models are target-agnostic. The source is `bigquery-public-data.thelook_ecommerce`
(the 7 tables below) and resolves like this:

```yaml
version: 2
sources:
  - name: thelook_ecommerce
    database: "{{ 'bigquery-public-data' if target.type == 'bigquery' else target.database }}"
    schema: thelook_ecommerce
    tables: [orders, order_items, users, products, inventory_items, distribution_centers, events]
```

* `target: bigquery` → `bigquery-public-data.thelook_ecommerce.<table>` (the real data).
* `target: duckdb`  → `dev.thelook_ecommerce.<table>` — a **local fixture** (section 2)
  that mirrors the real schema, types and value vocabularies.

`dev.thelook_ecommerce` is loaded out of band by `scripts/load_duckdb_sources.sh`. It is
not `dbt seed`: the fixture is generated SQL, not committed CSVs, and the BigQuery target
must never receive fixture data.

### Real source schemas (authoritative — do not invent columns or drop any silently)

| table | columns (source order) |
|---|---|
| `orders` | `order_id` INT64, `user_id` INT64, `status` STRING, `gender` STRING, `created_at` TIMESTAMP, `returned_at` TIMESTAMP, `shipped_at` TIMESTAMP, `delivered_at` TIMESTAMP, `num_of_item` INT64 |
| `order_items` | `id` INT64, `order_id` INT64, `user_id` INT64, `product_id` INT64, `inventory_item_id` INT64, `status` STRING, `created_at` TIMESTAMP, `shipped_at` TIMESTAMP, `delivered_at` TIMESTAMP, `returned_at` TIMESTAMP, `sale_price` FLOAT64 |
| `users` | `id` INT64, `first_name` STRING, `last_name` STRING, `email` STRING, `age` INT64, `gender` STRING, `state` STRING, `street_address` STRING, `postal_code` STRING, `city` STRING, `country` STRING, `latitude` FLOAT64, `longitude` FLOAT64, `traffic_source` STRING, `created_at` TIMESTAMP |
| `products` | `id` INT64, `cost` FLOAT64, `category` STRING, `name` STRING, `brand` STRING, `retail_price` FLOAT64, `department` STRING, `sku` STRING, `distribution_center_id` INT64 |
| `inventory_items` | `id` INT64, `product_id` INT64, `created_at` TIMESTAMP, `sold_at` TIMESTAMP, `cost` FLOAT64, `product_category` STRING, `product_name` STRING, `product_brand` STRING, `product_retail_price` FLOAT64, `product_department` STRING, `product_sku` STRING, `product_distribution_center_id` INT64 |
| `distribution_centers` | `id` INT64, `name` STRING, `latitude` FLOAT64, `longitude` FLOAT64 |
| `events` | `id` INT64, `user_id` INT64, `sequence_number` INT64, `session_id` STRING, `created_at` TIMESTAMP, `ip_address` STRING, `city` STRING, `state` STRING, `postal_code` STRING, `browser` STRING, `traffic_source` STRING, `uri` STRING, `event_type` STRING |

## 2. The DuckDB fixture (`scripts/`)

`scripts/load_duckdb_sources.sh` — bash, `set -euo pipefail`, run with the DuckDB 1.5.x CLI
(`duckdb`, on PATH or `DUCKDB_BIN=`), database file `dev.duckdb` in the repo root.

* `scripts/fixtures/thelook_ecommerce.sql` holds the generator SQL.
* The script **recreates** `dev.thelook_ecommerce.*` from scratch every run (idempotent:
  `CREATE SCHEMA IF NOT EXISTS` + `CREATE OR REPLACE TABLE`).
* It prints each table's row count, then **asserts referential integrity and exits non-zero**
  if any orphan exists (order_items → orders/users/products/inventory_items; orders → users;
  inventory_items → products; products → distribution_centers; events → users).
* Deterministic: `setseed(0.42)` (or an equivalent deterministic generator). Fixed volumes:

  | table | rows |
  |---|---|
  | distribution_centers | 10 |
  | products | 200 |
  | users | 400 |
  | inventory_items | 6000 |
  | orders | 3000 |
  | order_items | 8000 |
  | events | 20000 |

* **Types mirror what the DuckDB target really sees.** Real BigQuery columns map as:
  INT64 → `bigint`, FLOAT64 → `double`, STRING → `varchar`,
  and BigQuery `TIMESTAMP` → **`timestamptz`** (DuckDB's `bigquery` extension returns
  BigQuery TIMESTAMP as TIMESTAMPTZ, so the fixture must too, or the portability seam in
  section 3 goes untested).
* Value vocabularies must be realistic (they are asserted by `accepted_values` tests):
  * `orders.status`, `order_items.status`: `Complete`, `Shipped`, `Processing`, `Returned`, `Cancelled`
  * `users.traffic_source`, `events.traffic_source`: `Search`, `Organic`, `Facebook`, `Email`, `Display`
  * `events.event_type`: `home`, `department`, `product`, `cart`, `purchase`, `cancel`
  * `users.gender`: `M`, `F`; `orders.gender`: `M`, `F`
  * `products.department`: `Men`, `Women`; `products.category` from the real vocabulary
    (e.g. `Jeans`, `Sweaters`, `Tops & Tees`, `Swim`, `Active`, `Shorts`, `Outerwear & Coats`,
    `Dresses`, `Skirts`, `Pants`, `Accessories`, `Socks`, `Suits & Sport Coats`)
  * `product.brand`: real-ish jeans brands (e.g. `Levi's`, `Diesel`, `Calvin Klein`, `Carhartt`, `Volcom`)
* Coherence rules the fixture must satisfy (this is what makes the marts meaningful):
  * every `order_items.order_id`/`user_id` belongs to a matching `orders` row, and
    `orders.num_of_item` equals that order's `order_items` count;
  * `orders.user_id`/`order_items.user_id` agree with each other;
  * `orders.created_at <= order_items.created_at`, `shipped_at <= delivered_at`,
    `returned_at >= delivered_at` when non-null; `returned_at`/`shipped_at`/`delivered_at`
    are **nullable** (a returned item has `status = 'Returned'` and a non-null `returned_at`);
  * `inventory_items.sold_at` is non-null exactly when the unit has been sold, and
    `created_at <= sold_at`;
  * `users.created_at` (signup) precedes that user's first order;
  * `order_items.sale_price` > 0; `products.retail_price >= products.cost`;
  * `events.created_at` spans the same window as orders, `sequence_number` starts at 1 per session.

Makefile: add a `fixtures` target that runs the script, and make it a prerequisite of `duck`
(`duck: check-env fixtures`), so `make duck` is green end to end on a clean checkout.

## 3. Cross-target macros (`macros/`)

`macros/cross_target.sql` already has `string_type()` (varchar / string) and `to_string()`.
Keep them. Add, all `adapter.dispatch`ed with a `default__` (DuckDB) and a `bigquery__` branch:

| macro | duckdb (default) | bigquery |
|---|---|---|
| `money_type()` | `decimal(18,2)` | `numeric` |
| `float_type()` | `double` | `float64` |
| `timestamp_type()` | `timestamp` | `timestamp` |
| `to_utc_timestamp(expr)` | `timezone('UTC', cast(<expr> as timestamptz))` | `cast(<expr> as timestamp)` |
| `generate_surrogate_key(cols)` | `md5(concat_ws('\|\|', <cols>))` | `to_hex(md5(concat(<cols...>)))` |

`to_utc_timestamp` is the deliberate time-zone decision: BigQuery TIMESTAMP is an absolute
instant; DuckDB hands it back as TIMESTAMPTZ and casting that directly would use the session
time zone. Every `*_at` column in staging and above is therefore a **naive UTC timestamp**
returned by this macro, and the docs must say so.

`generate_surrogate_key` is needed where a grain has no single natural key (cohort month ×
activity month). Prefer natural keys everywhere else; do not add surrogate keys for decoration.

## 4. Layer conventions

* **staging/** — `stg_thelook__<entity>.sql`, materialised **view** (dbt_project.yml already
  says so). Rename + cast only, no joins, no business logic, no aggregation.
  * `id` → `<entity>_id` (e.g. `order_item_id`, `product_id`, `distribution_center_id`);
    `inventory_items.product_distribution_center_id` → `distribution_center_id`.
  * every id/int → `bigint`; money columns → `money_type()`; timestamps → `to_utc_timestamp()`
    (so they are naive UTC); strings → `string_type()`; floats → `float_type()`.
  * one staging model per source table, all 7. Document every column.
  * staging joins nothing. `stg_thelook__inventory_items` keeps the denormalised
    `product_*` columns that the source has (say so in the docs); it does not join `products`.
* **intermediate/** — `int_<entity>__<verb>.sql`, materialised **view**. The joins and
  aggregates that make the marts readable. No `select *`. State the grain in the model docs.
* **marts/** — materialised **table** (dbt_project.yml already says so).
  * facts `fct_*`, dimensions `dim_*`, aggregates `mart_*`.
  * **no `select *`**, explicit column lists everywhere.
  * the grain is in the name and in the model description.
  * money columns are `money_type()`, rates are `float_type()`; the currency is **USD** and
    must be stated in the docs.
  * any model with an `order by` must have a deterministic total order (break ties).
* Every model: a one-line-plus description stating grain, and a description on **every column**.
  Model docs go in `models/<layer>/_<x>__models.yml`; source docs in
  `models/staging/_thelook__sources.yml`.

### Tests (required, not optional)

* `unique` + `not_null` on **every key** of every mart and intermediate model, and on every
  staging primary key.
* `not_null` on every foreign key column.
* `relationships` across the marts: `fct_orders.user_id → dim_users`,
  `fct_order_items.order_id → fct_orders`, `fct_order_items.user_id → dim_users`,
  `fct_order_items.product_id → dim_products`,
  `fct_order_items.distribution_center_id → dim_distribution_centers`,
  `fct_inventory_items.product_id → dim_products`,
  `fct_inventory_items.distribution_center_id → dim_distribution_centers`,
  `dim_products.distribution_center_id → dim_distribution_centers`,
  `mart_product_performance.product_id → dim_products`,
  `mart_customer_summary.user_id → dim_users`.
* `accepted_values` on the status/gender/traffic_source/event_type columns named in section 2.
* Singular tests in `tests/` (cross-model invariants the generic tests cannot express):
  * `assert_no_orphan_order_items.sql` — every `order_items` row has an order, user and product
  * `assert_order_item_count_matches_orders.sql` — `orders.num_of_item` = count of its items
  * `assert_timestamps_are_before_after.sql` — created ≤ shipped ≤ delivered ≤ returned
    wherever the columns are non-null
  * `assert_order_item_created_at_is_plausible.sql` (added 2026-09-27) — the half of the
    above that the real dataset violates, kept as `severity: warn`
  Each is a `select` that returns **zero rows** when the invariant holds.

**Measured deviations (2026-09-27).** Three of the requirements above do not survive contact
with the real `bigquery-public-data.thelook_ecommerce`, so they are deviated from on purpose
and the evidence is in NOTES.md > "Measured against the real dataset": `not_null` is not
tested on `stg_thelook__events.user_id` or `int_events__sessions.user_id` (46.4% of real
events are anonymous traffic and now carry a `relationships` test instead); the
`accepted_values` list on `events.traffic_source` is the measured events vocabulary (Email,
Adwords, Facebook, YouTube, Organic), which is not the `users` one this section lists; and
the lifecycle ordering test is narrowed to the pairs the source honors, with the
`order_items.created_at` pairs beside it as a warning. Every other test in this section runs
strict and green against the real data.

## 5. The 28 models

Column lists below are the required *shape*; you may add clearly-justified columns, but do not
drop the named ones, and keep the grain exactly as stated.

### staging (7, views)

| model | also |
|---|---|
| `stg_thelook__orders` | `order_id` PK |
| `stg_thelook__order_items` | `id` → `order_item_id` PK |
| `stg_thelook__users` | `id` → `user_id` PK |
| `stg_thelook__products` | `id` → `product_id` PK |
| `stg_thelook__inventory_items` | `id` → `inventory_item_id` PK, `product_distribution_center_id` → `distribution_center_id` |
| `stg_thelook__distribution_centers` | `id` → `distribution_center_id` PK |
| `stg_thelook__events` | `id` → `event_id` PK |

### intermediate (11, views)

1. `int_order_items__enriched` — grain: order item. `order_item_id` PK, `order_id`, `user_id`,
   `product_id`, `inventory_item_id`, `distribution_center_id`, `order_item_status`,
   `order_status`, `sale_price`, `product_cost` (from `inventory_items.cost` in USD),
   `gross_margin` = sale_price − product_cost, `is_returned`, `order_item_created_at`,
   `order_created_at`, `order_date`, `shipped_at`, `delivered_at`, `returned_at`,
   `product_category`, `product_department`, `product_brand`, `user_traffic_source`.
2. `int_orders__item_rollup` — grain: order. `order_id` PK, `user_id`, `order_status`,
   `order_created_at`, `order_date`, `item_count`, `returned_item_count`, `gross_revenue`,
   `total_cost`, `gross_margin`, `is_fully_returned`.
3. `int_orders__daily` — grain: calendar date (UTC). `order_date` PK, `order_count`,
   `order_item_count`, `customer_count`, `gross_revenue`, `total_cost`, `gross_margin`,
   `returned_item_count`.
4. `int_users__lifetime_orders` — grain: user. `user_id` PK, `first_order_at`, `last_order_at`,
   `lifetime_orders`, `lifetime_items`, `lifetime_gross_revenue`, `lifetime_total_cost`,
   `lifetime_gross_margin`, `lifetime_returned_items`.
5. `int_users__first_order_cohort` — grain: user. `user_id` PK, `signup_at`,
   `first_order_at`, `cohort_month` (first day of the month of the first order, `timestamp_type()`).
6. `int_cohorts__user_months` — grain: user × order month. `user_month_key` (surrogate) PK,
   `user_id`, `cohort_month`, `activity_month`, `orders`, `items`, `revenue`.
7. `int_products__sales` — grain: product. `product_id` PK, `units_sold`, `orders_with_product`,
   `gross_revenue`, `total_cost`, `gross_margin`, `first_sold_at`, `last_sold_at`.
8. `int_products__returns` — grain: product. `product_id` PK, `units_sold`, `returned_units`,
   `return_rate` (float, 0..1).
9. `int_inventory_items__enriched` — grain: inventory item. `inventory_item_id` PK,
   `product_id`, `distribution_center_id`, `product_category`, `product_department`,
   `product_brand`, `product_name`, `product_sku`, `unit_cost`, `product_retail_price`,
   `created_at`, `sold_at`, `is_sold`, `days_to_sell` (float, null when unsold).
10. `int_inventory__by_product_center` — grain: product × distribution center.
    `product_center_key` (surrogate) PK, `product_id`, `distribution_center_id`,
    `inventory_units`, `open_units`, `sold_units`, `open_inventory_value`, `open_retail_value`.
11. `int_events__sessions` — grain: session. `session_id` PK, `user_id`, `first_event_at`,
    `last_event_at`, `session_seconds` (float), `event_count`, `max_sequence_number`,
    `traffic_source`, `browser`, `has_purchase`.

### marts (10, tables)

12. `fct_orders` — grain: order. From `int_orders__item_rollup` × `dim_users`.
    `order_id` PK; `user_id`, `order_status`, `order_created_at`, `order_date`, `order_month`,
    `item_count`, `returned_item_count`, `gross_revenue`, `total_cost`, `gross_margin`,
    `is_fully_returned`, `user_country`, `user_state`, `user_traffic_source`.
13. `fct_order_items` — grain: order item. From `int_order_items__enriched` × `dim_products` × `dim_users`.
    `order_item_id` PK; `order_id`, `user_id`, `product_id`, `inventory_item_id`,
    `distribution_center_id`, `order_item_status`, `order_status`, `sale_price`, `product_cost`,
    `gross_margin`, `is_returned`, `order_item_created_at`, `order_date`, `product_name`,
    `product_category`, `product_department`, `product_brand`, `product_retail_price`,
    `user_country`, `user_state`.
14. `dim_users` — grain: user. `user_id` PK; `first_name`, `last_name`, `email`, `age`, `gender`,
    `city`, `state`, `country`, `postal_code`, `traffic_source`, `signup_at`, `cohort_month`,
    `first_order_at`, `last_order_at`, `lifetime_orders`, `lifetime_items`,
    `lifetime_gross_revenue`, `lifetime_gross_margin`, `lifetime_returned_items`.
15. `dim_products` — grain: product. `product_id` PK; `product_name`, `sku`, `category`,
    `department`, `brand`, `distribution_center_id`, `distribution_center_name`, `unit_cost`,
    `retail_price`, `units_sold`, `gross_revenue`, `gross_margin`, `returned_units`, `return_rate`.
16. `dim_distribution_centers` — grain: distribution center. `distribution_center_id` PK; `name`,
    `latitude`, `longitude`, `inventory_units`, `open_units`, `sold_units`, `open_inventory_value`.
17. `fct_inventory_items` — grain: inventory item. `inventory_item_id` PK; `product_id`,
    `distribution_center_id`, `unit_cost`, `product_retail_price`, `created_at`, `sold_at`,
    `is_sold`, `days_to_sell`, `product_category`, `product_department`, `product_brand`.
18. `mart_daily_revenue` — grain: calendar date (UTC). `revenue_date` PK; `order_count`,
    `order_item_count`, `customer_count`, `gross_revenue`, `total_cost`, `gross_margin`,
    `average_order_value`, `returned_item_count`. `order by revenue_date`.
19. `mart_product_performance` — grain: product. `product_id` PK; `product_name`, `category`,
    `department`, `brand`, `unit_cost`, `retail_price`, `units_sold`, `gross_revenue`,
    `total_cost`, `gross_margin`, `gross_margin_rate`, `returned_units`, `return_rate`,
    `first_sold_at`, `last_sold_at`. `order by gross_revenue desc, product_id`.
20. `mart_customer_summary` — grain: user. `user_id` PK; `cohort_month`, `signup_at`,
    `first_order_at`, `last_order_at`, `months_active`, `lifetime_orders`, `lifetime_items`,
    `lifetime_gross_revenue`, `lifetime_gross_margin`, `average_order_value`,
    `returned_item_count`, `is_repeat_customer`.
21. `mart_cohort_retention` — grain: cohort month × activity month. `cohort_activity_key`
    (surrogate) PK; `cohort_month`, `activity_month`, `months_since_cohort` (bigint),
    `customers`, `orders`, `revenue`, `retention_rate` (float: cohort customers active in that
    month ÷ the cohort's month-0 customers). `order by cohort_month, activity_month`.
22. `dim_date` — **added by card 3 (t_44abf1ef), see section 7.6.** Grain: one row per UTC
    calendar date from the first to the last order date, inclusive. `date_day` (DATE) PK;
    `date_month`, `month_start_at`, `year_number`, `month_of_year`, `day_of_month`,
    `day_of_week_iso`, `is_weekend`, `days_since_first_order`. `order by date_day`.
    It is the model that makes the date macros load-bearing rather than dead code, and
    `mart_daily_revenue.revenue_date` has a `relationships` test against it.

Total: 7 + 11 + 11 = **29 models** (card 2 shipped 28; card 3 added `dim_date`, section 7.6).

## 6. Definition of done for the whole card

1. `make duck` exits 0 on a clean checkout (`dbt build --target duckdb`: 28 models built,
   all tests passing, seeds none).
2. `dbt build` is idempotent — run it twice, second run also exits 0.
3. `dbt parse --target bigquery` exits 0 (only proof available without credentials; call it
   out honestly as a parse, not a build).
4. Model count is 28 (in the 25–35 band). *(Card 3 raised it to 29 with `dim_date`, section
   7.6; still inside the band.)*
5. `README.md` states what is verified and what is not, with the real command output.
6. `NOTES.md` (this card) lists every source column deliberately dropped, renamed or cast,
   and why.

---

# SPEC — the transpile macro layer (card t_44abf1ef)

Everything below is the design contract for card 3. Sections 0–6 above are still authoritative
for the model tree and still describe the code you are editing. This card **moves** the
cross-target seam into `macros/polyglot/`, adds the macro families BigQuery and DuckDB differ on,
adds the guardrail that makes "portable" measurable, and adds one model that makes the new date
macros load-bearing instead of dead code.

Rules that do not change: never touch `main`, never commit, `profiles.yml` is off limits, no dbt
packages, `make duck` must stay green and idempotent, and **no model may contain a
`{% if target.type %}` branch** — divergence lives in `macros/` only.

## 7.1 Layout

```
macros/polyglot/types.sql       int_type, string_type, float_type, timestamp_type, money_type,
                                decimal_type(p,s), type_bigint_array
macros/polyglot/casting.sql     safe_cast, to_string, to_utc_timestamp
macros/polyglot/selection.sql   except_columns
macros/polyglot/structs.sql     struct_literal
macros/polyglot/arrays.sql      generate_series, generate_date_series
macros/polyglot/dates.sql       date_diff_days, format_date_str, format_month, timestamp_trunc_to,
                                day_of_week_iso, month_start, month_number, seconds_between
macros/polyglot/math.sql        safe_divide
macros/polyglot/strings.sql     regexp_contains
macros/polyglot/keys.sql        generate_surrogate_key
macros/polyglot/self_check.sql  polyglot_render, polyglot_selfcheck
analyses/polyglot_showcase.sql  one query that calls every macro (compiled, never run)
```

`macros/cross_target.sql` is **deleted**; its macros move into the files above with their names
and behaviour unchanged. Every macro keeps the existing house style: an entry-point macro that
does `{{ return(adapter.dispatch('<name>', 'bq_duckdb_experiments')()) }}`, a `default__<name>`
(DuckDB) branch and a `bigquery__<name>` branch, and a Jinja `{# ... #}` docstring on the
entry point that says **what it does and why the two dialects differ** (one paragraph; name the
concrete syntax on each side).

## 7.2 The macros (exact renderings — do not invent another spelling)

| macro | DuckDB (`default__`) | BigQuery | why they differ |
|---|---|---|---|
| `int_type()` | `bigint` | `int64` | BQ has one integer type, INT64; DuckDB's canonical 64-bit int is BIGINT |
| `string_type()` | `varchar` | `string` | DuckDB keeps the SQL-standard name |
| `float_type()` | `double` | `float64` | as above |
| `timestamp_type()` | `timestamp` | `timestamp` | same name, different meaning (see `to_utc_timestamp`) |
| `money_type()` | `decimal(18,2)` | `numeric` | BQ NUMERIC is fixed 38,9; DuckDB needs an explicit width/scale |
| `decimal_type(p,s)` | `decimal(p,s)`, **raises** when `p > 38` | `numeric` when `p <= 38 and s <= 9`, else `bignumeric` | DuckDB DECIMAL tops out at 38 digits; BIGNUMERIC has no DuckDB equivalent (rule below) |
| `type_bigint_array()` | `bigint[]` | `array<int64>` | DuckDB writes the `T[]` suffix, BQ the `ARRAY<T>` parameterised type |
| `safe_cast(expr, type)` | `try_cast(<expr> as <type>)` | `safe_cast(<expr> as <type>)` | BQ spells the NULL-on-failure cast SAFE_CAST; DuckDB spells it TRY_CAST |
| `to_string(expr)` | `cast(<expr> as varchar)` | `cast(<expr> as string)` | via `string_type()` (unchanged) |
| `to_utc_timestamp(expr)` | `timezone('UTC', cast(<expr> as timestamptz))` | `cast(<expr> as timestamp)` | unchanged; the deliberate time-zone decision |
| `except_columns(cols)` | `* exclude (a, b)` | `* except (a, b)` | BQ calls the star modifier EXCEPT, DuckDB calls it EXCLUDE |
| `struct_literal(fields)` | `{'a': 1, 'b': 2}` | `struct(1 as a, 2 as b)` | BQ's constructor takes named fields; DuckDB's struct literal is a map-like `{'k': v}` |
| `generate_series(a, b[, step])` | `generate_series(a, b[, step])` | `generate_array(a, b[, step])` | BQ's array generator is GENERATE_ARRAY, DuckDB's is GENERATE_SERIES |
| `generate_date_series(a, b, step)` | `cast(generate_series(a, b, interval <step>) as date[])` | `generate_date_array(a, b, interval <step>)` | BQ returns ARRAY<DATE>; DuckDB's date series is TIMESTAMP[], so the macro casts it back |
| `date_diff_days(later, earlier)` | `date_diff('day', <earlier>, <later>)` | `date_diff(<later>, <earlier>, day)` | the arguments are **reversed** between the engines |
| `format_date_str(expr, fmt)` | `strftime(<expr>, '<fmt>')` | `format_date(<expr>, '<fmt>')` | BQ's FORMAT_DATE vs DuckDB's STRFTIME |
| `format_month(expr)` | `strftime(<expr>, '%Y-%m')` | `format_date(<expr>, '%Y-%m')` | the one format the marts need |
| `timestamp_trunc_to(expr, g)` | `date_trunc('<g>', <expr>)` | `timestamp_trunc(<expr>, <g>)` | BQ's part is a bare keyword, DuckDB's is a quoted string; BQ has TIMESTAMP_TRUNC, DuckDB only DATE_TRUNC |
| `day_of_week_iso(expr)` | `extract(isodow from <expr>)` | `(extract(dayofweek from <expr>) + 6) % 7 + 1` | DuckDB's `isodow` is already ISO (Mon=1); BQ's `dayofweek` is Sun=1, so the macro must do arithmetic |
| `month_start(expr)` | unchanged | unchanged | now delegates to `timestamp_trunc_to(expr, 'month')` on DuckDB |
| `safe_divide(n, d)` | `cast(<n> as double) / nullif(cast(<d> as double), 0)` | `safe_divide(<n>, <d>)` | BQ's SAFE_DIVIDE is NULL-on-zero-division and returns FLOAT64; the DuckDB branch must reproduce both the semantics **and** the type |
| `regexp_contains(expr, pattern)` | `regexp_matches(<expr>, <pattern>)` | `regexp_contains(<expr>, <pattern>)` | same regex engine, different function name |
| `generate_surrogate_key(cols)` | unchanged | unchanged | the two `concat` semantics, documented already |
| `month_number(expr)`, `seconds_between(a,b)` | unchanged | unchanged | already portable branches |

Argument hygiene, all of it enforced with `exceptions.raise_compiler_error`:
`except_columns` with an empty list, `timestamp_trunc_to` with a granularity outside
`second|minute|hour|day|week|month|quarter|year`, `generate_date_series` with a step outside
`<n> (day|week|month|quarter|year)` (`n >= 1`), and `struct_literal` with an empty field list.
`unnest(...)` is **not** a macro: the name and semantics are identical on both engines — say that
in `arrays.sql` so nobody adds it later.

## 7.3 The decimal ceiling (the rule, decided here)

BigQuery NUMERIC is 38,9 and BIGNUMERIC is 76.76 digits (38 integer digits + 38 fractional).
DuckDB's DECIMAL is capped at **38 digits total** and rejects anything wider
(`Binder Error: DECIMAL type width must be between 1 and 38`).

The rule, implemented in `decimal_type(p, s)` and documented in its docstring:

* `p <= 38` → DuckDB `decimal(p, s)`; BigQuery `numeric` if `s <= 9` else `bignumeric`.
* `p > 38` → on BigQuery `bignumeric`; on DuckDB **`raise_compiler_error`** naming the ceiling and
  the two legal ways out (declare a narrower decimal, or `float_type()` and accept 15–16
  significant digits). It must **never** silently render `double`, because a silent float is
  exactly the failure mode the card calls out.

## 7.4 The guardrail: `scripts/check_portability.py`

Python 3 (stdlib only, `python3`), runnable from the repo root, exit 0 = portable, exit 1 = not.
It is the number the card asks for, so it must print counts, not adjectives.

1. **Compile both targets** into separate trees so both renders survive:
   `.venv/bin/dbt compile --target duckdb --target-path target/portability/duckdb` and the same with
   `--target bigquery` (export `DBT_PROFILES_DIR` to the repo root; the DuckDB leg needs the
   fixture, so tell the caller to run `make fixtures` when `dev.duckdb` is missing).
2. **Scan the compiled SQL** under `target/portability/<target>/compiled/bq_duckdb_experiments/`
   (both `models/` and `analyses/`), after **stripping SQL comments** (`--` to end of line and
   `/* */`) so prose cannot trip it. The transport measurement trees `analyses/transport_a/` and
   `analyses/transport_b/` are excluded (an explicit list, `EXCLUDED_ANALYSES`, in the script; the
   output reports how many compiled files each dropped): they are deliberately engine-specific
   scenarios run by the transport harnesses, compiled by dbt only because they sit under `analyses/`.
   * DuckDB render must not contain any BigQuery-only token:
     `float64`, `safe_cast`, `safe_divide`, `generate_array`, `generate_date_array`,
     `regexp_contains`, `format_date`, `timestamp_trunc`, `timestamp_diff`, `bignumeric`,
     `struct(`, `* except (`, `array<`, `date_diff(` not followed by a quote, `bigquery-public-data`.
   * BigQuery render must not contain any DuckDB-only token:
     `try_cast`, `regexp_matches`, `strftime`, `generate_series`, `list_value`, `struct_pack`,
     `epoch_ms`, `* exclude (`, `bigint[]`, `::`, `date_trunc('`, `date_diff('`, and
     `dev.thelook_ecommerce` (the BigQuery render must never name the local fixture catalog).
   * Every token in those lists was measured against DuckDB 1.5.5 (`int64` is *accepted* by DuckDB,
     so it is deliberately **not** a DuckDB-direction token; `float64` is rejected, so it is).
3. **Purity check**: no file under `models/` or `tests/` may contain `target.type`, `target.name`,
   `target.database`, `target.schema` or `adapter.type`. One allowlist entry, with its reason in the
   source: `models/staging/_thelook__sources.yml` (the source *database* name is the single thing
   that is genuinely target-dependent; it is declared in one line and cannot live in a model).
4. **Output**: one line per finding (`path:line: token 'x' -> <the line>`), then a summary of the
   form `compiled files checked: N (models: M, analyses: K)`, `BigQuery-only tokens in the DuckDB
   render: 0/15`, `DuckDB-only tokens in the BigQuery render: 0/13`, `target-branch findings: 0`,
   and `PORTABLE` or `NOT PORTABLE: n finding(s)`. Exit accordingly.
5. **`--demo`** proves the guardrail can fail. It writes a temporary
   `models/intermediate/_portability_demo.sql` containing both a raw BigQuery-only call
   (`select regexp_contains('a','a') as demo`) and a `{% if target.type == 'bigquery' %}` branch,
   recompiles the DuckDB leg, asserts the checker now reports ≥1 finding of each kind with the demo
   file named in the output, deletes the file (in a `finally`), re-checks, asserts clean, and prints
   `demo: the guardrail failed as designed, then passed again`. It exits 0 only if both halves held.

Makefile: add `polyglot` (`check-env` + `fixtures` + `bash scripts/polyglot_check.sh`) and
`portability` (`check-env` + `python3 scripts/check_portability.py`), with help lines. Leave
`duck`, `bq`, `build-both` and `parity` as they are.

`scripts/polyglot_check.sh` (bash, `set -euo pipefail`) is the whole macro layer in one command:
`check_env.sh`; `load_duckdb_sources.sh`; `dbt run-operation polyglot_selfcheck --target duckdb`;
`dbt run-operation polyglot_render --target duckdb` and `--target bigquery` (tee both to
`target/polyglot_render_<target>.txt`); `python3 scripts/check_portability.py`; then
`python3 scripts/check_portability.py --demo`. Each step prints its own pass/fail line.

## 7.5 `polyglot_render` and `polyglot_selfcheck` (the macros' own tests)

`dbt run-operation` works on **both** targets on this machine, including `--target bigquery`
with no credentials, as long as the macro does not query the warehouse (verified).

* `polyglot_render(include_bignumeric=false)` — for the current target, `log()` one line per macro
  invocation in the form `render <macro-name> <target.type> :: <rendered sql>`. With
  `include_bignumeric=true` it also renders `decimal_type(77,38)`, which therefore **fails on
  DuckDB by design** (that is how the ceiling rule is demonstrated) and prints `bignumeric` on
  BigQuery.
* `polyglot_selfcheck()` — DuckDB only. For every macro it builds a SQL expression, runs it with
  `run_query`, and compares against the expected value/type using `typeof()` where the type is the
  point. Print `selfcheck ok  <name>` / `selfcheck FAIL <name> expected <x> got <y>`, and
  `raise_compiler_error` at the end if anything failed. On a non-DuckDB target it logs
  `selfcheck skipped: <target.type> cannot be executed here (no credentials; render-only)` and
  exits 0. Required cases (the card's ten dialect differences plus the type macros), all with
  constant inputs so they are deterministic:
  `safe_cast('42', int_type())` = 42 and `typeof` `BIGINT`; `safe_cast('nope', int_type())` = null;
  `safe_divide(1, 0)` = null; `safe_divide(1, 4)` = 0.25 with `typeof` `DOUBLE`;
  `date_diff_days(date '2024-03-15', date '2024-03-01')` = 14;
  `format_month(timestamp '2024-03-15 13:45:00')` = `2024-03`;
  `timestamp_trunc_to(timestamp '2024-03-15 13:45:12', 'hour')` = `2024-03-15 13:00:00`;
  `day_of_week_iso(date '2024-03-15')` = 5 (a Friday);
  `generate_series(1, 5)` = `[1,2,3,4,5]`, `generate_series(1, 9, 3)` = `[1,4,7]`,
  `sum(unnest(...))` shape check;
  `generate_date_series(date '2024-03-01', date '2024-03-05')` has 5 elements and `typeof` `DATE[]`;
  `regexp_contains('LifeOS', '^Life')` = true and `regexp_contains('LifeOS', '^Nope')` = false;
  `except_columns(['b'])` used as `select {{ except_columns(['b']) }} from (select 1 as a, 2 as b)`
  returns exactly the columns `[a]`;
  `struct_literal([['a', 1], ['b', 2]])` gives `s.a` = 1, `s.b` = 2 on both engines' access syntax;
  `typeof(cast([] as {{ type_bigint_array() }}))` = `BIGINT[]`;
  `typeof(...)` of `int_type()`, `string_type()`, `float_type()`, `timestamp_type()`,
  `money_type()`, `decimal_type(38, 9)` = `BIGINT`, `VARCHAR`, `DOUBLE`, `TIMESTAMP`,
  `DECIMAL(18,2)`, `DECIMAL(38,9)`.
  Where an expression cannot be written as `select <expr>` (the star modifier), use the shape above
  and check the returned column names rather than a value.

## 7.6 Models this card touches

Behaviour-preserving refactors (the rendered SQL and every number must be unchanged):

* every `cast(<x> as bigint)` in `models/` → `cast(<x> as {{ int_type() }})`;
* `int_products__returns.return_rate` → `{{ safe_divide('item_returns.returned_units', 'item_returns.units_sold') }}`;
* `mart_product_performance.gross_margin_rate` → `{{ safe_divide('sales.gross_margin', 'sales.gross_revenue') }}`;
* `mart_cohort_retention.retention_rate` → `{{ safe_divide('cohort_months.customers', 'cohort_sizes.cohort_customers') }}`;
* `month_start()` keeps its call sites and now delegates to `timestamp_trunc_to(expr, 'month')`.
* **Leave** `mart_daily_revenue.average_order_value` and `mart_customer_summary.average_order_value`
  as decimal division (`round(x / nullif(y, 0), 2)` cast to `money_type()`): they want *decimal*
  rounding, and `safe_divide` is float-typed on purpose (that is BigQuery's SAFE_DIVIDE). Note this
  in the `safe_divide` docstring and in the README's "where a macro could not hide the difference"
  list.

One new model, `models/marts/dim_date.sql` (29 models total, still inside the 25–35 band) — the
model that stops the date macros being dead code. Grain: **one row per UTC calendar date from the
first to the last order date, inclusive**. Built from `int_orders__daily` for the min/max, expanded
with `unnest(generate_date_series(min_date, max_date))`. Columns: `date_day` (**DATE**, PK),
`date_month` (`string_type()`, via `format_month`), `month_start_at` (`timestamp_type()`, via
`month_start`), `year_number`, `month_of_year`, `day_of_month` (ints, `int_type()`),
`day_of_week_iso` (via `day_of_week_iso`), `is_weekend` (boolean, `day_of_week_iso >= 6`),
`days_since_first_order` (`int_type()`, via `date_diff_days(date_day, first_date)`). Document the
model and every column in `models/marts/_marts__models.yml`; tests: `unique` + `not_null` on
`date_day`, `not_null` on `date_month`, `month_start_at`, `day_of_week_iso`, `is_weekend`,
`days_since_first_order`, `accepted_values` on `is_weekend`, and
`mart_daily_revenue.revenue_date → dim_date.date_day` as a `relationships` test.

## 7.7 Definition of done for this card

1. `make duck` exits 0 (29 models + every test) and is idempotent; nothing regresses.
2. `dbt ls --resource-type model --quiet --target duckdb | wc -l` → 29.
3. `dbt compile --target bigquery` exits 0; `dbt run-operation polyglot_render --target bigquery`
   exits 0 and prints a BigQuery rendering for every macro.
4. `dbt run-operation polyglot_selfcheck --target duckdb` exits 0 with every case `ok`.
5. `dbt run-operation polyglot_render --args '{include_bignumeric: true}' --target duckdb` **fails**
   with the decimal-ceiling message (expected failure, captured), and the same command with
   `--target bigquery` prints `bignumeric`.
6. `python3 scripts/check_portability.py` exits 0 with the counts printed;
   `python3 scripts/check_portability.py --demo` exits 0 having shown it report findings and then
   pass again; `bash scripts/polyglot_check.sh` (i.e. `make polyglot`) exits 0.
7. `README.md` documents the macro layer (the table above, with a "load-bearing in a model" vs
   "exercised by the self-check" column), the guardrail with its real output, the decimal-ceiling
   rule, and a **"where a macro could not hide the difference"** list containing at least: the
   decimal ceiling, DuckDB's TIMESTAMP[] date series vs BigQuery's ARRAY<DATE>, division typing
   (decimal vs float64), and the source-database name outside `macros/`.
8. `NOTES.md` gets a card-3 section with the real command output, the count of macros, and which
   dialect difference was hardest.
9. Report the total macro count at the end of `NOTES.md` and in the run summary.
