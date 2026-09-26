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
  Each is a `select` that returns **zero rows** when the invariant holds.

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

Total: 7 + 11 + 10 = **28 models**.

## 6. Definition of done for the whole card

1. `make duck` exits 0 on a clean checkout (`dbt build --target duckdb`: 28 models built,
   all tests passing, seeds none).
2. `dbt build` is idempotent — run it twice, second run also exits 0.
3. `dbt parse --target bigquery` exits 0 (only proof available without credentials; call it
   out honestly as a parse, not a build).
4. Model count is 28 (in the 25–35 band).
5. `README.md` states what is verified and what is not, with the real command output.
6. `NOTES.md` (this card) lists every source column deliberately dropped, renamed or cast,
   and why.
