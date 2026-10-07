# NOTES — card t_d0cac5da, phase 1 (macros, source, fixture, staging)

Scope: SPEC sections 1, 2, 3, 4 and the staging table in section 5. No intermediate or
mart model exists yet. Nothing is committed. `profiles.yml`, `dbt_project.yml` and
`packages.yml` are untouched.

## Files

Created:

| file | what |
|---|---|
| `models/staging/_thelook__sources.yml` | source `thelook_ecommerce`, 7 tables; database is `bigquery-public-data` on BigQuery and `target.database` (`dev`) otherwise; every table and column documented |
| `models/staging/_thelook__models.yml` | docs for all 7 staging models and every column; 40 generic tests |
| `models/staging/stg_thelook__{orders,order_items,users,products,inventory_items,distribution_centers,events}.sql` | the 7 staging views |
| `scripts/fixtures/thelook_ecommerce.sql` | the generator SQL for the DuckDB fixture |
| `scripts/load_duckdb_sources.sh` | loads the fixture into `dev.duckdb`, prints row counts, runs 22 integrity/coherence checks, exits 1 if any fails |
| `scripts/fixtures/coherence_assertions_staging.sql` | my own coherence assertions, run on the staging views |
| `NOTES.md` | this file |

Modified:

* `macros/cross_target.sql`: added `money_type()`, `float_type()`, `timestamp_type()`,
  `to_utc_timestamp(expr)` and `generate_surrogate_key(cols)`, each `adapter.dispatch`ed with
  a `default__` (DuckDB) and a `bigquery__` branch. `string_type()` and `to_string()` are unchanged.
* `Makefile`: new `fixtures` target (`bash scripts/load_duckdb_sources.sh`),
  `duck: check-env fixtures`, plus the matching `.PHONY` and help lines.

## Spec problems and deviations (read these first)

1. **The fixed volumes contradict "one unit per order item" (SPEC section 2).** The spec
   requires 8000 `order_items` but only 6000 `inventory_items`. Every order item carries a
   non-null `inventory_item_id`. In the real dataset each order item consumes its own
   inventory unit. That cannot happen here, because 8000 > 6000. I kept the spec's volumes
   (they are stated as fixed) and did not stop, because no stated rule is actually broken:
   the orphan check, the product match (`order_items.product_id = inventory_items.product_id`),
   "`sold_at` is non-null exactly when the unit has been sold" and `created_at <= sold_at` all
   hold. **The cost is that some units are sold more than once:**

   | order items referencing the unit | units |
   |---|---|
   | 0 (open stock) | 800 |
   | 1 | 2419 |
   | 2 | 2762 |
   | 3 | 19 |

   `sold_at` is the unit's **first** sale. For later phases this means
   `fct_order_items.inventory_item_id` is **not unique**. `days_to_sell` and `sold_units`
   count a unit once, while its order items count every sale. **Decision for Bruno:** keep this,
   or raise `inventory_items` to at least 8000 plus some open stock (for example 10000). The
   change is two constants in the fixture (`range(1, 6001)` and the `% 26` slot count).

2. **`generate_surrogate_key`, BigQuery branch.** The spec's
   `to_hex(md5(concat(<cols...>)))` is a type error in BigQuery for any non-STRING column,
   because `concat` accepts only STRING/BYTES and the planned keys use ids and months. The
   branch therefore wraps each column in `to_string()`:
   `to_hex(md5(concat(cast(a as string), cast(b as string))))`. As specified, the two targets
   also hash **different strings**: DuckDB joins the columns with a `'||'` separator and BigQuery
   uses none. So surrogate key *values* will not match across targets, and a parity check that
   compares keys will fail. I did not add a separator on the BigQuery side, because that would
   change the spec's formula further. Say if you want it. This branch has not been executed
   (no BigQuery credentials).

3. **Probable mismatches with the real BigQuery data — both confirmed on 2026-09-27, and
   both fixed; see "Measured against the real dataset" below for the numbers.**
   * Real `events.user_id` **is** null for anonymous traffic: 1,124,610 of 2,425,698 rows.
     SPEC section 4 requires `not_null` on every foreign key, so the staging `not_null` test
     on `events.user_id` passed on the fixture and failed on BigQuery; it was removed and
     replaced by a `relationships` test on the non-null values.
   * Real `events.traffic_source` **does** use a different vocabulary from `users` (Email,
     Adwords, Facebook, YouTube, Organic — the earlier guess was close). The spec gives both
     the users vocabulary, so the `accepted_values` test failed on BigQuery; its list and the
     fixture's events vocabulary now both carry the measured set.

4. **Determinism is hash-based rather than `random()`.** `setseed(0.42)` is called, but
   `random()` is only reproducible single-threaded in DuckDB. Every draw is therefore
   `hash(<row key>, '<salt>')`, a pure function of the row (the "equivalent deterministic
   generator" the spec allows). Measured: two consecutive loads produced identical md5
   fingerprints for every table (below).

5. **Additions beyond the spec's minimum** (all pass): `not_null` on `status`, `created_at`,
   `session_id` and `event_type`; `accepted_values` on `products.department` (Men/Women). No
   staging `relationships` tests: the spec asks for them across the marts, and the loader
   already checks integrity on the fixture.

## Source columns dropped, renamed or cast

**Dropped: none.** Every column of the 7 source tables is in its staging model, in source order.

**Renamed** (SPEC section 4, `id` → `<entity>_id`):

| source | staging | why |
|---|---|---|
| `order_items.id` | `order_item_id` | entity-qualified primary key |
| `users.id` | `user_id` | same |
| `products.id` | `product_id` | same |
| `inventory_items.id` | `inventory_item_id` | same |
| `distribution_centers.id` | `distribution_center_id` | same |
| `events.id` | `event_id` | same |
| `inventory_items.product_distribution_center_id` | `distribution_center_id` | SPEC section 4; it is the FK to distribution centers |

`orders.order_id` already has the right name. No other columns are renamed.

**Cast** (DuckDB type → staging type):

| source type (BigQuery / fixture) | staging | columns | why |
|---|---|---|---|
| INT64 / BIGINT | `bigint` | every id, `num_of_item`, `age`, `sequence_number`, `distribution_center_id`, `inventory_item_id` | SPEC: every id/int is bigint (explicit, so the type does not depend on the source) |
| FLOAT64 / DOUBLE | `money_type()` = `decimal(18,2)` / `numeric` | `order_items.sale_price`, `products.cost`, `products.retail_price`, `inventory_items.cost`, `inventory_items.product_retail_price` | money is fixed-point, USD; FLOAT64 sums drift |
| FLOAT64 / DOUBLE | `float_type()` = `double` / `float64` | `users.latitude/longitude`, `distribution_centers.latitude/longitude` | coordinates are not money |
| TIMESTAMP / TIMESTAMPTZ | `to_utc_timestamp()` → naive `timestamp` in UTC | every `*_at` column (`created_at`, `shipped_at`, `delivered_at`, `returned_at`, `sold_at`) | SPEC section 3's time-zone decision. A plain cast would use the session time zone, which is Europe (+01/+02) on this machine (see below) |
| STRING / VARCHAR | `string_type()` | every string column | cross-target type |

The money cast rounds to 2 decimal places. The fixture's prices are generated at 2 dp, so
nothing is lost here. On real data it does round: measured 2026-09-27,
`order_items.sale_price` is within 1.5e-05 of its 2 dp rounding (float noise, nothing lost),
but `products.cost` is off by half a cent or more in 7,923 of 29,120 rows — see NOTES.md >
"Measured against the real dataset".

## Commands run and their real output

### `bash scripts/load_duckdb_sources.sh` → exit 0

```
Loading scripts/fixtures/thelook_ecommerce.sql into dev.duckdb (schema thelook_ecommerce)

Row counts:
  distribution_centers       10
  products                  200
  users                     400
  inventory_items          6000
  orders                   3000
  order_items              8000
  events                  20000

Integrity and coherence checks (violating rows):
  ok    orphan order_items.order_id -> orders                              0
  ok    orphan order_items.user_id -> users                                0
  ok    orphan order_items.product_id -> products                          0
  ok    orphan order_items.inventory_item_id -> inventory_items            0
  ok    orphan orders.user_id -> users                                     0
  ok    orphan inventory_items.product_id -> products                      0
  ok    orphan products.distribution_center_id -> distribution_centers     0
  ok    orphan events.user_id -> users                                     0
  ok    order_items.user_id <> orders.user_id                              0
  ok    orders.num_of_item <> count(order_items)                           0
  ok    order_items.product_id <> inventory_items.product_id               0
  ok    orders.created_at > order_items.created_at                         0
  ok    created > shipped > delivered > returned (orders)                  0
  ok    created > shipped > delivered > returned (order_items)             0
  ok    status/returned_at mismatch (Returned <=> returned_at not null)    0
  ok    inventory_items: sold_at set <> unit referenced by an order item   0
  ok    inventory_items.created_at > sold_at                               0
  ok    users.created_at >= first order                                    0
  ok    order_items.sale_price <= 0                                        0
  ok    products.retail_price < cost                                       0
  ok    sessions not starting at sequence_number 1                         0
  ok    events before the user signed up                                   0

Fixture loaded and coherent.
```

Fixture types, from `information_schema.columns`: every INT64 column is `BIGINT`, every
FLOAT64 column is `DOUBLE`, every STRING column is `VARCHAR`, and every TIMESTAMP column is
`TIMESTAMP WITH TIME ZONE`. Column order matches the SPEC table exactly.

Distributions: orders by status are Complete 750, Shipped 932, Processing 605, Cancelled 424
and Returned 289. `num_of_item` is 1×500, 2×800, 3×900 and 4×800 (sum 8000). Events by type
are home 4021, department 4020, product 7403, cart 2278, purchase 1822 and cancel 456, across
4021 sessions. All 400 users have orders and events.

### Determinism: load twice, fingerprint every table

Regenerated 2026-09-27 with the recipe below, after two consecutive `make fixtures` loads
produced identical output. The `events` fingerprint had to change because the fixture's
`events.traffic_source` moved to the measured real vocabulary (see "Measured against the
real dataset"); the recipe is `md5` of one `to_json` per row, all rows in primary-key
order, one statement per table:

```
select 'orders|' || md5(string_agg(to_json(o), chr(10)))
from (select * from thelook_ecommerce.orders order by order_id) o;
```

```
orders|d0ac1cafdeec4e7a3a2433cc5459a30a
order_items|c715b54b6733acd61c19aa6d77860124
users|a7000458daae7280c3d0471f2ae56c7d
products|67ec94658ba42fab3783e003463d22ec
inventory_items|9e8e17ba746555f4a85abc6609b8e589
events|22c87fc50f6eac34f9e2e184b4d4e7c6
inventory units: sold|8000 unsold|2000 referenced by >1 order item|0
```

### `make duck` → exit 0 (first run)

```
 Succeeded model main.stg_thelook__orders (view) [3 of 47 in 0.30s]
 Succeeded model main.stg_thelook__inventory_items (view) [5 of 47 in 0.29s]
 Succeeded model main.stg_thelook__distribution_centers (view) [7 of 47 in 0.32s]
 Succeeded model main.stg_thelook__order_items (view) [4 of 47 in 0.36s]
 Succeeded model main.stg_thelook__products (view) [2 of 47 in 0.39s]
 Succeeded model main.stg_thelook__events (view) [6 of 47 in 0.40s]
 Succeeded model main.stg_thelook__users (view) [1 of 47 in 0.45s]
    Passed test  ... (40 tests, all Passed)
=================== Errors and Warnings ====================
[warning] [UnusedResourceConfigPath (dbt1097)]: Configuration paths exist in your dbt_project.yml file which do not apply to any resources.
There are 2 unused configuration paths:
- models.bq_duckdb_experiments.intermediate
- models.bq_duckdb_experiments.marts
==================== Execution Summary =====================
Finished 'build' with 1 warning for target 'duckdb' [3.0s]
Processed: 7 models | 40 tests
Summary: 47 total | 47 success
```

This includes `check-env` (all `ok`) and the fixture load above. The one warning is expected:
there are no intermediate or mart models yet.

### `make duck` → exit 0 (second run, idempotency)

The full run was captured to `logs/duck_run2.log`: `check-env` all ok, the fixture was reloaded
with all 22 checks `ok`, and the build ended with:

```
Finished 'build' with 1 warning for target 'duckdb' [3.3s]
Processed: 7 models | 40 tests
Summary: 47 total | 47 success
```

### The source resolves to the fixture on DuckDB

`target/compiled/.../stg_thelook__orders.sql`: `select * from "dev"."thelook_ecommerce"."orders"`.

### Staging timestamps are naive UTC, whatever the session time zone

The session was set to `America/Los_Angeles`, then source and staging were compared:

```
│ source_tstz              │ stg_naive           │ equals_utc │
│ 2025-03-29 16:31:00-07   │ 2025-03-29 23:31:00 │ true       │
│ 2023-11-15 08:52:40-08   │ 2023-11-15 16:52:40 │ true       │
mismatches (created_at, shipped_at over all 3000 orders): 0
```

Staging types (DuckDB): ids `BIGINT`, money `DECIMAL(18,2)`, coordinates `DOUBLE`, `*_at` as
`TIMESTAMP` (naive), strings `VARCHAR`.

### My coherence assertions on the staging views

`duckdb dev.duckdb -f scripts/fixtures/coherence_assertions_staging.sql`:

```
│ orphan order_items (order/user/product/inventory)                   │ 0 │
│ orphan orders -> users                                              │ 0 │
│ orphan events -> users                                              │ 0 │
│ orphan inventory_items -> products / distribution_centers           │ 0 │
│ orders.num_of_item <> count(order_items)                            │ 0 │
│ order_items created before order                                    │ 0 │
│ created <= shipped <= delivered <= returned broken (items)          │ 0 │
│ inventory created_at > sold_at                                      │ 0 │
│ inventory distribution_center_id <> products.distribution_center_id │ 0 │
│ sum(num_of_item) (expect 8000)                                      │ 0 │

orders_from 2022-02-16 13:34:04  orders_to 2025-12-31 19:30:29   (UTC)
events_from 2022-01-22 09:14:01  events_to 2025-12-31 17:45:15   (UTC)
```

## Not run (and why)

* **`dbt parse --target bigquery`**: the command was refused by this session's tool permissions,
  so it has not been run in this phase. It is the next thing to run. It proves only that the
  project renders for that target, not that the BigQuery SQL is valid.
* **The loader's failing path** (a fixture with an injected orphan, via `FIXTURE_SQL=`): also
  refused by this session's permissions, together with writes to `/tmp`. The exit-1 branch has
  therefore not been exercised; only the green path has.
* **Any BigQuery execution**: there are no credentials. The `bigquery__` macro branches have never run.

---

# NOTES — phase 2 (fixture/macro corrections, intermediate layer)

Scope: Bruno's two corrections to phase 1 (A.1 fixture volumes, A.2 surrogate key) and the
11 intermediate views in SPEC section 5. No marts model exists. Nothing is committed.
Staging, `profiles.yml`, `dbt_project.yml` and `packages.yml` are untouched. **This section
supersedes phase 1's "Spec problems" items 1 and 2**, which are now resolved as described below.

## Files

Created:

| file | what |
|---|---|
| `models/intermediate/int_order_items__enriched.sql` | grain: order item |
| `models/intermediate/int_orders__item_rollup.sql` | grain: order |
| `models/intermediate/int_orders__daily.sql` | grain: UTC order date |
| `models/intermediate/int_users__lifetime_orders.sql` | grain: user |
| `models/intermediate/int_users__first_order_cohort.sql` | grain: user |
| `models/intermediate/int_cohorts__user_months.sql` | grain: user × order month, surrogate `user_month_key` |
| `models/intermediate/int_products__sales.sql` | grain: product |
| `models/intermediate/int_products__returns.sql` | grain: product |
| `models/intermediate/int_inventory_items__enriched.sql` | grain: inventory item |
| `models/intermediate/int_inventory__by_product_center.sql` | grain: product × distribution center, surrogate `product_center_key` |
| `models/intermediate/int_events__sessions.sql` | grain: session |
| `models/intermediate/_int__models.yml` | model docs (grain stated in each), every column described, 53 generic tests |
| `scripts/fixtures/grain_checks_intermediate.sql` | my grain + reconciliation checks, run with the DuckDB CLI |

Modified:

* `scripts/fixtures/thelook_ecommerce.sql`: inventory_items now has 10000 units. Order item *i*
  consumes unit *i* (same product), and units 8001..10000 are open stock (10 per product,
  `1 + (i - 8001) % 200`). This took more than "two constants": the phase-1 round-robin slot
  scheme could not make unit id = order item id, so I rewrote the `order_item_units` mapping and
  the `units` CTE (about 15 lines). All other tables and volumes are unchanged. `sold_at` is
  still computed as "the unit's first sale"; each unit now has only one sale.
* `scripts/load_duckdb_sources.sh`: two new checks, `inventory units referenced by more than
  one order item` and `order_items.inventory_item_id is null`. There are now 24 checks (was 22).
* `macros/cross_target.sql`
  * `bigquery__generate_surrogate_key` now puts `'||'` between the parts:
    `to_hex(md5(concat(cast(a as string), '||', cast(b as string))))`. That is the same string
    DuckDB's `md5(concat_ws('||', a, b))` hashes. Both return lowercase hex.
  * New dispatched macros:
    * `month_start(expr)`: DuckDB `cast(date_trunc('month', x) as timestamp)`, BigQuery
      `timestamp_trunc(x, month)`.
    * `seconds_between(start, end)`: DuckDB `date_diff('microsecond', …)`, BigQuery
      `timestamp_diff(…, microsecond)`, both cast to `float_type()` and divided by 1e6.
  * New plain macro `month_number(expr)`: the yyyymm integer via `extract`, which has the same
    syntax on both engines.

## Spec problems and decisions (phase 2)

1. **Surrogate keys only match across targets if their parts render as the same text.** The
   separator fix is necessary but not enough on its own. In DuckDB, `cast(timestamp as varchar)`
   gives `2024-03-01 00:00:00`. In BigQuery, `cast(TIMESTAMP as STRING)` gives
   `2024-03-01 00:00:00+00` (from BigQuery's documented format; not executed here). So
   `user_month_key` is built from `user_id` and `month_number(activity_month)` (e.g. `202403`),
   not from the month timestamp. `product_center_key` uses two bigints. The macro's comment now
   says to use only integer or string parts. On DuckDB, every `user_month_key` equals
   `md5(user_id || '||' || strftime(activity_month, '%Y%m'))`. Whether the BigQuery hash matches
   has **not** been executed.
2. **"Gross" includes every status.** SPEC does not say whether Cancelled or Returned items count
   towards revenue. Every `gross_revenue`, `total_cost`, `gross_margin`, `units_sold` and
   `lifetime_*` column counts all order items, whatever their status. Returns are reported in
   separate columns (`returned_item_count`, `returned_units`, `return_rate`), and the model docs
   say so. If the marts should net out cancellations or returns, that is a phase-3 decision.
3. **"Grain: user" and "grain: product" keep every row.** The `int_users__*` and
   `int_products__*` models start from the staging table and left-join the aggregates. Users or
   products with no activity therefore still appear, with zero totals and null `first_order_at`,
   `cohort_month`, `first_sold_at` or `return_rate`. In the fixture every user has orders and
   every product has sales (29..58 units), so no nulls occur. On real data they will.
4. **`int_orders__daily` has no date spine.** Only dates with at least one order appear (1040
   of the 1415 days from 2022-02-16 to 2025-12-31). SPEC says "grain: calendar date". If
   `mart_daily_revenue` needs zero rows for days without orders, phase 3 needs a date spine.
5. **`is_fully_returned` means the order has items and every item is 'Returned'.** In the
   fixture, items inherit the order status, so it is true for exactly the 289 'Returned' orders.
6. **`int_events__sessions.user_id` has no `not_null` test** (it had one per SPEC section 4;
   measured 2026-09-27, 500,000 of the real 681,313 sessions are anonymous on every event, so
   the test was removed — see "Measured against the real dataset"). `user_id` is the
   session's `max(user_id)`, so a session that logs in part-way still gets its user.
7. **`int_inventory__by_product_center` lists only (product, center) pairs that have stock**, not
   every product × center combination. Each product is stocked at one center in the fixture, so
   it has 200 rows.
8. **`days_to_sell` and `session_seconds` are floats with microsecond precision.** Days are
   `seconds_between() / 86400`. The fixture range of `days_to_sell` is 1.04..120.98.

## Source-column decisions (phase 2)

| intermediate column | taken from | why |
|---|---|---|
| `int_order_items__enriched.product_cost` | `inventory_items.cost` | SPEC; the cost of the unit actually sold |
| `int_order_items__enriched.distribution_center_id` | `inventory_items.product_distribution_center_id` (staging `distribution_center_id`) | the center the unit shipped from; equals `products.distribution_center_id` in the fixture |
| `int_order_items__enriched.product_category/department/brand` | `products` | the product table, not the unit's denormalised copy |
| `int_order_items__enriched.order_date` | `cast(orders.created_at as date)` | the UTC date of the order, not of the item |
| `int_order_items__enriched.is_returned` | `order_items.status = 'Returned'` | status, not `returned_at`; the loader proves the two agree |
| `int_orders__item_rollup.item_count` | `count(order_items)` | counted, not the source's `num_of_item` (phase 3's singular test compares them) |
| `int_cohorts__user_months.activity_month` | month of `orders.created_at` | the order's month, not the item's |
| `int_users__first_order_cohort.cohort_month` | month of `min(orders.created_at)` | an order of any status counts as a first order |
| `int_inventory_items__enriched.product_*`, `unit_cost` | the denormalised `inventory_items` columns | SPEC section 4: no join to products |
| `int_events__sessions.traffic_source`, `browser` | the session's first event (lowest `sequence_number`, ties by `event_id`) | one deterministic value per session |

No source column was dropped (staging is unchanged).

## Commands run and their real output (phase 2)

### `bash scripts/load_duckdb_sources.sh` → exit 0

```
Loading scripts/fixtures/thelook_ecommerce.sql into dev.duckdb (schema thelook_ecommerce)

Row counts:
  distribution_centers       10
  products                  200
  users                     400
  inventory_items         10000
  orders                   3000
  order_items              8000
  events                  20000

Integrity and coherence checks (violating rows):
  ok    orphan order_items.order_id -> orders                              0
  ok    orphan order_items.user_id -> users                                0
  ok    orphan order_items.product_id -> products                          0
  ok    orphan order_items.inventory_item_id -> inventory_items            0
  ok    orphan orders.user_id -> users                                     0
  ok    orphan inventory_items.product_id -> products                      0
  ok    orphan products.distribution_center_id -> distribution_centers     0
  ok    orphan events.user_id -> users                                     0
  ok    order_items.user_id <> orders.user_id                              0
  ok    orders.num_of_item <> count(order_items)                           0
  ok    order_items.product_id <> inventory_items.product_id               0
  ok    orders.created_at > order_items.created_at                         0
  ok    created > shipped > delivered > returned (orders)                  0
  ok    created > shipped > delivered > returned (order_items)             0
  ok    status/returned_at mismatch (Returned <=> returned_at not null)    0
  ok    inventory_items: sold_at set <> unit referenced by an order item   0
  ok    inventory units referenced by more than one order item             0
  ok    order_items.inventory_item_id is null                              0
  ok    inventory_items.created_at > sold_at                               0
  ok    users.created_at >= first order                                    0
  ok    order_items.sale_price <= 0                                        0
  ok    products.retail_price < cost                                       0
  ok    sessions not starting at sequence_number 1                         0
  ok    events before the user signed up                                   0

Fixture loaded and coherent.
```

New fixture row counts: distribution_centers 10, products 200, users 400, **inventory_items
10000**, orders 3000, order_items 8000, events 20000. Of the 10000 units, 8000 are sold and 2000
open. Each product has 39..68 units, 10 of them open. Measured through the views:
`sum(sold_units)` = 8000 and `sum(open_units)` = 2000. Open stock is worth 75,579.20 USD at
cost and 160,355.10 USD at retail.

### `make duck` → exit 0 (first run)

```
=================== Errors and Warnings ====================
[warning] [UnusedResourceConfigPath (dbt1097)]: Configuration paths exist in your dbt_project.yml file which do not apply to any resources.
There are 1 unused configuration paths:
- models.bq_duckdb_experiments.marts

==================== Execution Summary =====================
Finished 'build' with 1 warning for target 'duckdb' [4.3s]
Processed: 18 models | 93 tests
Summary: 111 total | 111 success
```

18 models = 7 staging + 11 intermediate. 93 tests = 40 staging + 53 intermediate. The warning
is expected because there are no marts yet.

### `make duck` → exit 0 (second and third runs, idempotency)

Both runs were captured, to `logs/phase2_duck_run2.log` and `logs/phase2_duck_run3.log`. The
third was a bare `make duck > log` and the tool reported exit status 0 for `make` itself. Both
logs show the fixture reloaded with all 24 checks `ok` and end with:

```
Finished 'build' with 1 warning for target 'duckdb' [4.6s]      (run 3: [4.9s])
Processed: 18 models | 93 tests
Summary: 111 total | 111 success
```

### Grain checks: `duckdb -readonly dev.duckdb -f scripts/fixtures/grain_checks_intermediate.sql`

| model | key | rows | distinct keys | null keys | grain ok |
|---|---|---|---|---|---|
| int_order_items__enriched | order_item_id | 8000 | 8000 | 0 | true |
| int_orders__item_rollup | order_id | 3000 | 3000 | 0 | true |
| int_orders__daily | order_date | 1040 | 1040 | 0 | true |
| int_users__lifetime_orders | user_id | 400 | 400 | 0 | true |
| int_users__first_order_cohort | user_id | 400 | 400 | 0 | true |
| int_cohorts__user_months | user_month_key | 2544 | 2544 | 0 | true |
| int_cohorts__user_months | (user_id, activity_month) | 2544 | 2544 | 0 | true |
| int_products__sales | product_id | 200 | 200 | 0 | true |
| int_products__returns | product_id | 200 | 200 | 0 | true |
| int_inventory_items__enriched | inventory_item_id | 10000 | 10000 | 0 | true |
| int_inventory__by_product_center | product_center_key | 200 | 200 | 0 | true |
| int_inventory__by_product_center | (product_id, distribution_center_id) | 200 | 200 | 0 | true |
| int_events__sessions | session_id | 4021 | 4021 | 0 | true |

The same file's reconciliation checks all returned `true`:

* 8000 = `sum(item_count)`.
* `inventory_item_id` is unique in `int_order_items__enriched`.
* Gross revenue is identical in staging, daily, users, products and cohorts.
* 10000 units = 8000 sold + 2000 open.
* Sessions cover all 20000 events.
* `return_rate` is in [0, 1] (observed 0.0..0.265).
* `days_to_sell` is null exactly when the unit is unsold, and ≥ 0 otherwise.
* `cohort_month <= activity_month`, and both are month starts (43 cohorts, 2022-02..2025-09).
* `user_month_key = md5(user_id || '||' || yyyymm)`.

DuckDB column types (from information_schema): months `TIMESTAMP`, money `DECIMAL(18,2)`,
rates and durations `DOUBLE`, counts `BIGINT`, flags `BOOLEAN`, `order_date` `DATE`.

### `dbt compile --target bigquery` → exit 0

```
[warning] [UnusedResourceConfigPath (dbt1097)]: ... - models.bq_duckdb_experiments.marts
==================== Execution Summary =====================
Finished 'compile' with 1 warning for target 'bigquery' [1.2s]
Processed: 18 models | 93 tests
Summary: 111 total | 111 success
```

Rendered BigQuery SQL, from `target/compiled/.../intermediate/`:

```
int_inventory__by_product_center: to_hex(md5(concat(cast(product_id as string), '||', cast(distribution_center_id as string))))
int_cohorts__user_months:         to_hex(md5(concat(cast(user_months.user_id as string), '||', cast((extract(year from user_months.activity_month) * 100 + extract(month from user_months.activity_month)) as string))))
int_cohorts__user_months:         timestamp_trunc(order_created_at, month)
int_inventory_items__enriched:    cast(timestamp_diff(sold_at, created_at, microsecond) as float64) / 1000000.0 / 86400.0
```

`dbt parse --target bigquery` also exits 0 (`Finished 'parse' with 1 warning for target 'bigquery'`).

**This is all the BigQuery evidence there is.** Compile renders the Jinja for the BigQuery
adapter without executing anything. It does not prove that the SQL is valid BigQuery, that the
types line up, or that the surrogate keys equal DuckDB's. No BigQuery query has been run,
because there are no credentials.

---

# NOTES — phase 3 (marts, singular tests, README)

Scope: the 10 mart tables in SPEC section 5, their docs and tests; the 3 singular tests in
SPEC section 4; README.md. Nothing is committed. Staging, intermediate, `profiles.yml`,
`dbt_project.yml` and `packages.yml` are untouched (so are the fixture, the loader and the
macros).

## Files

Created:

| file | what |
|---|---|
| `models/marts/fct_orders.sql` | grain: order |
| `models/marts/fct_order_items.sql` | grain: order item |
| `models/marts/fct_inventory_items.sql` | grain: inventory item |
| `models/marts/dim_users.sql` | grain: user |
| `models/marts/dim_products.sql` | grain: product |
| `models/marts/dim_distribution_centers.sql` | grain: distribution center |
| `models/marts/mart_daily_revenue.sql` | grain: UTC order date; `order by revenue_date` |
| `models/marts/mart_product_performance.sql` | grain: product; `order by gross_revenue desc, product_id` |
| `models/marts/mart_customer_summary.sql` | grain: user |
| `models/marts/mart_cohort_retention.sql` | grain: cohort month × activity month, surrogate `cohort_activity_key`; `order by cohort_month, activity_month` |
| `models/marts/_marts__models.yml` | every model's grain and every column documented (USD stated); 63 generic tests |
| `tests/assert_no_orphan_order_items.sql` | every order item has an order, user and product, and its `user_id` equals its order's |
| `tests/assert_order_item_count_matches_orders.sql` | `orders.num_of_item` = count of its items = `fct_orders.item_count` |
| `tests/assert_timestamps_are_before_after.sql` | created ≤ shipped ≤ delivered ≤ returned (every non-null pair) for `orders`, and shipped ≤ delivered ≤ returned for `order_items` |
| `tests/assert_order_item_created_at_is_plausible.sql` | `order_items.created_at` follows the lifecycle and its order — `severity: warn`, because the real dataset violates it (see "Measured against the real dataset") |
| `logs/phase3_*.log` | the captured runs quoted below |

Modified: `README.md` (rewritten to the real state; structure and "Known dbt v2 findings"
kept, findings 8–11 added).

## Decisions and spec problems (phase 3)

1. **`order by` in a table model does not give the table an order.** SPEC asks for a
   deterministic total order on three marts, and each has one (`revenue_date` is the key;
   `gross_revenue desc, product_id` and `cohort_month, activity_month` end in the grain).
   A table has no row order, though. DuckDB happens to keep insertion order for a simple
   scan. BigQuery does not guarantee any order for `select * from table`. Consumers must
   still `order by`. The clause was kept because SPEC asks for it; it compiles for BigQuery,
   where `order by` in a CTAS is legal (unexecuted).
2. **`mart_daily_revenue` has no date spine** (phase 2 item 4 carried forward). There is one
   row per UTC date with at least one order: 1040 of the 1415 days in the fixture's range.
   SPEC names the grain "calendar date (UTC)" and does not ask for zero rows. A spine would
   need a new dispatched macro (`range()` vs `generate_date_array`) with an unexecuted
   BigQuery branch, so it was not added. The model docs say days without orders are absent.
3. **`average_order_value` is explicitly `round(x, 2)`.** `money_type()` is `decimal(18,2)`
   on DuckDB, so the cast alone would round to cents. On BigQuery it is `numeric`, scale 9,
   so the same expression would keep 9 decimal places and the two targets would differ. It
   is found by reading the compiled SQL; the BigQuery value itself has never been computed.
   All other mart money columns are sums of 2-dp values, where this does not arise.
4. **`retention_rate` in month 0 is 1.0 by construction.** The cohort is the month of the
   first order, so every cohort member is active in month 0 and the denominator ("the
   cohort's month-0 customers") is the cohort size. Measured: 0 month-0 rows ≠ 1.0; range
   0.0625..1.0. Only (cohort, activity month) pairs with at least one active member have a
   row, so there are no explicit zero-retention rows.
5. **`months_since_cohort`** is `(year diff) * 12 + (month diff)` using `extract`, which is
   spelt the same on both engines, so no new macro was needed.
6. **`unit_cost` is ambiguous in the SPEC.** `dim_products.unit_cost` and
   `mart_product_performance.unit_cost` are the catalogue `products.cost`.
   `fct_inventory_items.unit_cost` is the unit's own `inventory_items.cost`. Margins
   everywhere use the unit's cost, via `int_order_items__enriched.product_cost`. In the
   fixture the two costs are equal for all 10000 units, and so are retail price and
   distribution center (measured: 0 differences each). The real data may differ.
7. **`mart_product_performance` is not built on `dim_products`.** It needs `total_cost`,
   `first_sold_at` and `last_sold_at`, which `dim_products` does not carry, so it reads
   staging + `int_products__sales` + `int_products__returns` directly. It still has the
   SPEC's `relationships` test to `dim_products`.
8. **`int_events__sessions` feeds no mart.** SPEC section 5 lists no sessions or events mart,
   so no mart uses the 11th intermediate model. It is built and tested. Events data
   therefore reaches no mart.
9. **Additions beyond the SPEC minimum** (all pass): `unique` + `not_null` +
   `relationships → fct_inventory_items` on `fct_order_items.inventory_item_id` (a unit is
   sold at most once, which holds only if the fixture's one-unit-per-item shape holds for
   the real data too); `not_null` on `fct_orders.order_created_at`/`order_date`/`order_month`,
   `dim_users.signup_at`, `fct_inventory_items.unit_cost`/`created_at`/`is_sold`, the
   cohort months and `months_since_cohort`, and on `fct_order_items.sale_price` and
   `product_cost`; `accepted_values` on `dim_products.department` and
   `fct_orders.user_traffic_source`.
10. **The singular tests read staging, not the marts**, except that the count test also
    checks `fct_orders.item_count`. The invariants are about the source data. Staging is
    rename-and-cast only, so it is the closest checkable layer, and a violation there is
    reported regardless of how the marts are built. The orphan test adds the one check a
    `relationships` test cannot make (`order_items.user_id = orders.user_id`).
11. **The fixture has 399 repeat customers out of 400**, so `is_repeat_customer` is nearly
    constant. That is a fixture artefact and says nothing about the real repeat rate.

## Source columns dropped, renamed or cast — whole card

**Staging (phases 1–2): nothing dropped.** Every column of the 7 source tables is in its
staging view. The renames and casts are listed in phase 1's table above and are unchanged.

**Renamed further up the stack** (all the SPEC's names):

| source column | mart column | where |
|---|---|---|
| `orders.status` | `order_status` | `fct_orders`, `fct_order_items` |
| `order_items.status` | `order_item_status` | `fct_order_items` |
| `orders.created_at` | `order_created_at`, and `order_date` / `order_month` / `revenue_date` derived from it | `fct_orders`, `fct_order_items`, `mart_daily_revenue` |
| `order_items.created_at` | `order_item_created_at` | `fct_order_items` |
| `inventory_items.cost` | `product_cost` (fct_order_items), `unit_cost` (fct_inventory_items) | |
| `products.cost` | `unit_cost` | `dim_products`, `mart_product_performance` |
| `products.name` | `product_name` | `dim_products`, `mart_product_performance`, `fct_order_items` |
| `products.retail_price` | `product_retail_price` | `fct_order_items` |
| `users.created_at` | `signup_at` | `dim_users`, `mart_customer_summary` |
| `users.country/state/traffic_source` | `user_country/user_state/user_traffic_source` | `fct_orders`, `fct_order_items` |
| `distribution_centers.name` | `distribution_center_name` | `dim_products` |

**Cast further up:** nothing new. Counts are `bigint`, money is `money_type()`, and rates
are `float_type()` computed from those. `average_order_value` is rounded to 2 dp (decision 3).

**Source columns that reach no mart** (in staging, deliberately not carried; SPEC's mart
column lists do not name them):

| source | columns | why |
|---|---|---|
| `users` | `street_address`, `latitude`, `longitude` | not in SPEC's `dim_users` list; street-level PII and coordinates have no mart consumer |
| `orders` | `gender` (duplicate of `users.gender`), `num_of_item` (checked by the singular test; `item_count` is counted instead), `shipped_at`, `delivered_at`, `returned_at` | not in SPEC's `fct_orders` list |
| `order_items` | `shipped_at`, `delivered_at`, `returned_at` | in `int_order_items__enriched` but not in SPEC's `fct_order_items` list; `is_returned` carries the return |
| `inventory_items` | `product_name`, `product_sku` (the unit's denormalised copies; `dim_products` has the product's own) | not in SPEC's `fct_inventory_items` list |
| `events` | all 13 columns | only `int_events__sessions` uses events, and no mart reads it (decision 8) |

`products.*` and `distribution_centers.*` all reach a mart.

## Commands run and their real output (phase 3)

### `make duck` → exit 0 (first run, after the final edit)

`logs/phase3_duck_run1.log`: `check-env` all 7 `ok`, fixture reloaded (same row counts as
phase 2, all 24 checks `ok`), then:

```
==================== Execution Summary =====================
Finished 'build' successfully for target 'duckdb' [8.3s]
Processed: 28 models | 159 tests
Summary: 187 total | 187 success
```

No warnings. The phase-2 `UnusedResourceConfigPath` warning for `marts` is gone.

### `make duck` → exit 0 (second run, idempotency)

`logs/phase3_duck_run2.log`, with the fixture reloaded again and all 24 checks `ok`:

```
Finished 'build' successfully for target 'duckdb' [5.8s]
Processed: 28 models | 159 tests
Summary: 187 total | 187 success
```

(A first pair of runs, before the `round(x, 2)` edit of decision 3, was also 187/187.)

159 tests = 40 staging + 53 intermediate + 63 marts (generic) + 3 singular. The 63 were
counted with `dbt ls --resource-type test --select path:models/marts --quiet`. That lists
64, because it also selects `assert_order_item_count_matches_orders`, which refs `fct_orders`.

### The `relationships` tests (all Passed in run 2)

The SPEC's 10 cross-mart tests:

```
relationships_fct_orders_user_id__user_id__ref_dim_users_
relationships_fct_order_items_order_id__order_id__ref_fct_orders_
relationships_fct_order_items_user_id__user_id__ref_dim_users_
relationships_fct_order_items_product_id__product_id__ref_dim_products_
relationships_fct_order_items_distribution_center_id__distribution_center_id__ref_dim_distribution_centers_
relationships_fct_inventory_items_product_id__product_id__ref_dim_products_
relationships_fct_inventory_items_distribution_center_id__distribution_center_id__ref_dim_distribution_centers_
relationships_dim_products_distribution_center_id__distribution_center_id__ref_dim_distribution_centers_
relationships_mart_product_performance_product_id__product_id__ref_dim_products_
relationships_mart_customer_summary_user_id__user_id__ref_dim_users_
```

Plus `relationships_fct_order_items_inventory_item_id__inventory_item_id__ref_fct_inventory_items_`
(an addition), and phase 2's three intermediate ones.

### Singular tests (run 2)

```
    Passed test  assert_no_orphan_order_items [38 of 187 in 0.32s]
    Passed test  assert_timestamps_are_before_after [42 of 187 in 0.39s]
    Passed test  assert_order_item_count_matches_orders [183 of 187 in 0.23s]
```

No YAML declaration was needed (README v2 finding 9). **Their failing path has not been
exercised**: no fixture with an injected violation was run through them.

### `dbt compile --target bigquery` → exit 0; `dbt parse --target bigquery` → exit 0

```
Finished 'compile' successfully for target 'bigquery' [1.9s]
Processed: 28 models | 159 tests
Summary: 187 total | 187 success
```
```
Finished 'parse' successfully for target 'bigquery' [829ms]
```

Rendered mart SQL for BigQuery (`target/compiled/.../marts/`), for example:

```
fct_orders:               timestamp_trunc(orders.order_created_at, month)    as order_month,
mart_cohort_retention:    to_hex(md5(concat(cast((extract(year from cohort_months.cohort_month) * 100 + extract(month from cohort_months.cohort_month)) as string), '||', cast((extract(year from cohort_months.activity_month) * 100 + extract(month from cohort_months.activity_month)) as string))))
mart_product_performance: cast(sales.gross_margin as float64) / nullif(cast(sales.gross_revenue as float64), 0)    as gross_margin_rate,
staging (all 7):          select * from `bigquery-public-data`.`thelook_ecommerce`.`<table>`
```

As in phase 2, this is rendering only. Nothing was executed on BigQuery.

### `dbt ls --resource-type model --target duckdb | wc -l` → `36` (not 28)

v2 prints its banner, a `Selected nodes` header and the summary to stdout: 28 node lines
plus 8 others (listed in full; 10 marts, 11 intermediate, 7 staging). With `--quiet` the
same command gives `28`.

### Mart grains and row counts (`dbt show --inline`, run after run 2)

| mart | grain | key | rows | distinct keys |
|---|---|---|---|---|
| fct_orders | order | order_id | 3000 | 3000 |
| fct_order_items | order item | order_item_id | 8000 | 8000 |
| fct_inventory_items | inventory unit | inventory_item_id | 10000 | 10000 |
| dim_users | user | user_id | 400 | 400 |
| dim_products | product | product_id | 200 | 200 |
| dim_distribution_centers | distribution center | distribution_center_id | 10 | 10 |
| mart_daily_revenue | UTC order date | revenue_date | 1040 | 1040 |
| mart_product_performance | product | product_id | 200 | 200 |
| mart_customer_summary | user | user_id | 400 | 400 |
| mart_cohort_retention | cohort month × activity month | cohort_activity_key | 864 | 864 |

Reconciliation (one `dbt show`): `sum(stg_thelook__order_items.sale_price)` = `fct_orders`
= `fct_order_items` = `mart_daily_revenue` = `mart_product_performance` =
`mart_customer_summary` = `mart_cohort_retention` = **642483.63**. `open_inventory_value`
summed over `dim_distribution_centers` = 75579.2 (phase 2 measured 75,579.20). Retention
range 0.0625..1.0; month-0 rows ≠ 1.0: 0. `average_order_value` range 18.78..478.07.

DuckDB types (information_schema): money `DECIMAL(18,2)` (including `average_order_value`),
rates `DOUBLE`, months `TIMESTAMP`, `revenue_date` `DATE`, `months_since_cohort` `BIGINT`,
flags `BOOLEAN`.

### `dbt show` samples (real output; invented fixture data)

Top products by gross revenue:

```
│ product_id ┆ product_name                                     ┆ brand         ┆ units_sold ┆ gross_revenue ┆ gross_margin ┆ gm_rate ┆ return_rate │
│ 64         ┆ Lucky Brand Women's Classic Pants                ┆ Lucky Brand   ┆ 57         ┆ 8572.8        ┆ 3919.89      ┆ 0.4572  ┆ 0.1053      │
│ 170        ┆ Calvin Klein Women's Essential Pants             ┆ Calvin Klein  ┆ 50         ┆ 7467.         ┆ 4062.        ┆ 0.544   ┆ 0.16        │
│ 21         ┆ Volcom Women's Everyday Dresses                  ┆ Volcom        ┆ 50         ┆ 7145.5        ┆ 3090.5       ┆ 0.4325  ┆ 0.06        │
│ 131        ┆ Columbia Women's Essential Pants                 ┆ Columbia      ┆ 47         ┆ 6732.28       ┆ 3961.63      ┆ 0.5885  ┆ 0.0638      │
│ 6          ┆ True Religion Men's Slim Fit Suits & Sport Coats ┆ True Religion ┆ 51         ┆ 6703.44       ┆ 3565.92      ┆ 0.532   ┆ 0.0392      │
```

Daily revenue, last three dates (after the `round` edit):

```
│ revenue_date ┆ order_count ┆ order_item_count ┆ customer_count ┆ gross_revenue ┆ total_cost ┆ gross_margin ┆ average_order_value ┆ returned_item_count │
│ 2025-12-31   ┆ 5           ┆ 13               ┆ 5              ┆ 1120.82       ┆ 505.36     ┆ 615.46       ┆ 224.16              ┆ 0                   │
│ 2025-12-30   ┆ 6           ┆ 19               ┆ 6              ┆ 1635.6        ┆ 768.48     ┆ 867.12       ┆ 272.6               ┆ 0                   │
│ 2025-12-29   ┆ 6           ┆ 11               ┆ 6              ┆ 788.44        ┆ 402.18     ┆ 386.26       ┆ 131.41              ┆ 1                   │
```

Customers by cohort month (`mart_customer_summary`, first six cohorts; 2022-05 has none):

```
│ cohort_month ┆ customers ┆ orders ┆ revenue  ┆ repeat_customers │
│ 2022-02-01   ┆ 1         ┆ 7      ┆ 1520.64  ┆ 1                │
│ 2022-03-01   ┆ 2         ┆ 18     ┆ 4457.24  ┆ 2                │
│ 2022-04-01   ┆ 3         ┆ 27     ┆ 6103.13  ┆ 3                │
│ 2022-06-01   ┆ 5         ┆ 42     ┆ 8509.82  ┆ 5                │
│ 2022-07-01   ┆ 6         ┆ 41     ┆ 10335.28 ┆ 6                │
│ 2022-08-01   ┆ 13        ┆ 102    ┆ 22292.88 ┆ 13               │
```

Cohort retention, first cohort:

```
│ cohort_month ┆ activity_month ┆ months_since_cohort ┆ customers ┆ orders ┆ revenue ┆ retention_rate │
│ 2022-02-01   ┆ 2022-02-01     ┆ 0                   ┆ 1         ┆ 1      ┆ 240.25  ┆ 1.0            │
│ 2022-02-01   ┆ 2022-07-01     ┆ 5                   ┆ 1         ┆ 1      ┆ 148.89  ┆ 1.0            │
│ 2022-02-01   ┆ 2023-05-01     ┆ 15                  ┆ 1         ┆ 1      ┆ 309.44  ┆ 1.0            │
│ 2022-02-01   ┆ 2024-01-01     ┆ 23                  ┆ 1         ┆ 1      ┆ 217.48  ┆ 1.0            │
│ 2022-02-01   ┆ 2025-07-01     ┆ 41                  ┆ 1         ┆ 1      ┆ 243.93  ┆ 1.0            │
```

A `dbt show --inline` whose query ended in its own `limit 50` failed with
`Parser Error: syntax error at or near "limit"`: v2 appends its own limit (README finding 11).

## Not run (and why)

* **`make parity` could not show parity.** It was run from this worktree and exits 2:
  the DuckDB leg prints the ten marts' fixtures row counts, the BigQuery leg prints
  `n/a` for all ten, and the script says so. `dbt show --target bigquery` fails to
  authenticate before any query is sent, so nothing ran against BigQuery, and the
  two legs read different data (fixture vs `bigquery-public-data`), so equal counts
  are not even expected. `scripts/parity.sh` still prints the card-1 "VACUOUS ...
  Card 1 ships an empty skeleton" message when no marts exist; that text is stale
  but unreachable now (untouched, out of scope).
* **Any BigQuery execution.** No credentials.

## Measured against the real dataset (2026-09-27)

Card `t_d87cf14b`. The service account's grants landed, so `make bq`
(`dbt build --target bigquery`, dataset `coreychimpbot.experiments_dev`) ran against
`bigquery-public-data.thelook_ecommerce` for the first time. The first run exited 1 with
**three** failed tests, not the two the card named: the harness that found them printed only
the first lines of dbt's failure block. Clearing those exposed a fourth failure that had been
masked by dbt skipping 122 nodes downstream of the first one. Every number here is a query
against the real tables, not the fixture.

| # | test | failed rows | what the real data says |
| - | ---- | ----------: | ----------------------- |
| 1 | `not_null_stg_thelook__events_user_id` | 1,124,610 | 46.4% of 2,425,698 events carry no user at all (anonymous traffic). Every non-null id resolves: 0 orphans. |
| 2 | `accepted_values_stg_thelook__events_traffic_source__Search__Organic__Facebook__Email__Display` | 2 distinct values | `events.traffic_source` is exactly Email, Adwords, Facebook, YouTube, Organic over all 2,425,698 rows. The tested list was the **users** vocabulary; `users.traffic_source` really is Search, Organic, Facebook, Email, Display. |
| 3 | `assert_timestamps_are_before_after` | 137,795 | `orders` are clean: 0 of 124,952 violate any ordering pair. But 35,535 of 181,313 `order_items` are "created" after they shipped, and 102,260 are created before their own order (median -0.44 h, min -3.95 h, max +96.4 h). |
| 4 | `accepted_values_dim_date_is_weekend__True__False` | n/a — it cannot compile | Not a data problem: dbt renders `accepted_values` literals as quoted strings, so the test asked BigQuery for `BOOL not in ('True','False')` → `Error 400: No matching signature for operator IN for argument types BOOL and {STRING}`. DuckDB coerces, BigQuery refuses. This one was only reachable once the staging failures stopped skipping `dim_date`. |

Also measured, because it decides whether the marts can run at all once the staging tests
pass: 500,000 of the 681,313 real sessions have no user on any of their events, so
`not_null_int_events__sessions_user_id` would have failed next (it was skipped when the
staging test failed, together with the other 122 nodes downstream of the failing test).

### The decisions

1. **`user_id` on events and sessions: the assertion was false, so it is gone — the column
   and the fact stay.** Null `user_id` is not a defect, it is what the source means by
   anonymous traffic; 46% of a web event stream. Filtering those events in
   `stg_thelook__events` would delete 1.1M real rows from every funnel, and coalescing them
   to a sentinel would invent a user that `dim_users` does not contain. So the model keeps
   the nulls, the two `not_null` tests are removed (a deliberate SPEC section 4 deviation),
   and the invariant that *is* true — a non-null `user_id` resolves to a user — is asserted
   instead by a `relationships` test on `stg_thelook__events.user_id` (the first staging
   `relationships` test in the project, added for exactly this purpose). The measured
   numbers are in the column descriptions.
2. **`traffic_source`: the test was right to be strict and wrong about its list — the list
   is now the measured one.** Relaxing it to `severity: warn` would have made a permanent
   warning out of something that is simply the case, and documenting the divergence without
   fixing the list would leave the build red forever. The real events vocabulary
   (Email, Adwords, Facebook, YouTube, Organic) is now asserted strictly on both
   `stg_thelook__events` and `int_events__sessions`, and the DuckDB **fixture was corrected**
   to draw its events' `traffic_source` from that same set (it was drawing the users one),
   so the strict test means the same thing on both legs and a genuinely new value still
   fails. `users.traffic_source` keeps the users vocabulary, which is measured correct.
3. **Lifecycle ordering: split, because the two halves have different truth values.** The
   pairs that hold on the real data (all six for `orders`, the shipped/delivered/returned
   triple for `order_items`) stay a strict assertion in
   `tests/assert_timestamps_are_before_after.sql`. The pairs involving
   `order_items.created_at` — which the published dataset violates in a fifth to a half of
   its rows, because it jitters that timestamp around the order — moved to
   `tests/assert_order_item_created_at_is_plausible.sql` with `severity: warn` and the
   measured counts in the header. Deleting them would have hidden a real property of the
   source; leaving them strict would have kept the BigQuery leg red forever and, worse, kept
   dbt from building anything downstream of staging, since a failed test skips its children.
   A warning reports the dirt on every run and fails nothing.
4. **`dim_date.is_weekend`: the fourth failure was a portability bug in a vacuous test, so it
   is gone and the reason is recorded.** `accepted_values` on a boolean column cannot work on
   BigQuery — dbt quotes the literals — and on a column the model *computes* as
   `day_of_week_iso(date_day) >= 6` the test could only ever see `true`, `false` or null,
   which `not_null` already covers. Every other boolean in the project is tested `not_null`
   only; this one now matches, and the column description in
   `models/marts/_marts__models.yml` carries the trap so nobody re-adds it.

Nothing was deleted to get a green build: two false statements were replaced with the
measured truth (and one of them with a *new* test that watches the useful direction), and
the one genuinely dirty invariant is now a warning instead of an error.

### Verification

```
$ make duck     # exit 0, 197 tests, 197 success (fixture leg, after the fixture change)
$ make bq       # exit 0, the BigQuery leg builds all 29 models and runs every test
```

Still unmeasured after this card: the rows/values parity question (the legs read different
data by design) and the two data-quality assumptions in items 4 and 6 below.

## Remaining unverified assumptions (whole card)


1. **Everything about the real dataset.** Row counts, distributions, date range, and how
   many bytes a build scans against `maximum_bytes_billed` (1 GB). Every number in this file
   comes from the invented fixture.
2. **`events.user_id` is null for anonymous traffic — measured 2026-09-27.** 1,124,610 of
   2,425,698 real events (46.4%) carry no user, and 500,000 of 681,313 sessions are
   anonymous on every event. The two `not_null` tests were therefore removed and the
   non-null values are guarded by a `relationships` test instead; see "Measured against the
   real dataset".
3. **`events.traffic_source` does not use the users vocabulary — measured 2026-09-27.** The
   real events table carries exactly Email, Adwords, Facebook, YouTube and Organic over
   2,425,698 rows; `users.traffic_source` does carry Search, Organic, Facebook, Email and
   Display, so the mart tests that read it were right. Both `accepted_values` tests on the
   events column now assert the measured events set, and the fixture emits that same set so
   the test is identical on both legs; see "Measured against the real dataset".
4. **One inventory unit per order item — measured 2026-09-27, it holds.** 0 of the real
   181,313 order items share an `inventory_item_id`, so the `unique` tests in
   `int_order_items__enriched` and `fct_order_items` pass on the real data too.
5. **Every real order has ≥1 item and `num_of_item` matches — measured 2026-09-27, it
   holds** (`assert_order_item_count_matches_orders` passes on the real 124,952 orders). The
   lifecycle half of the same assumption does *not* hold for `order_items`; see "Measured
   against the real dataset".
6. **Real prices and costs have ≤ 2 decimal places — measured 2026-09-27, the prices do and
   the costs do not.** `order_items.sale_price` differs from its 2-decimal rounding by at
   most 1.5e-05 (float noise: 0 of 181,313 rows are off by half a cent or more), so rounding
   it costs nothing. `products.cost` is a different matter: 7,923 of 29,120 rows (27%) are
   off by half a cent or more (max 0.005), i.e. the `money_type()` cast really does round
   real costs, and a unit's `gross_margin` can move by half a cent because of it. Left as
   is: SPEC asks for money types, and half a cent per unit is below the reporting grain —
   but it is measured now, not assumed.
7. **`inventory_items.cost` = `products.cost`**, and the unit's denormalised retail price and
   distribution center equal the product's. This is true in the fixture (0 differences) and
   still unverified on real data (item 6 measured the rounding, not this equality).
8. **Every real `order_items.user_id` equals its order's `user_id` — measured 2026-09-27, it
   holds**: 0 mismatches over 181,313 items.
9. **Real `users.created_at` precedes the first order, and all statuses and genders are in
   the SPEC vocabularies — measured 2026-09-27, all hold**: 0 user/first-order violations,
   and the `accepted_values` tests on every status and gender column pass on the real data.
10. **Every `bigquery__` macro branch and all 28 models' rendered BigQuery SQL — executed
    2026-09-27.** The whole DAG now builds against the real dataset (`make bq` exit 0), so
    `timestamp_trunc`, `timestamp_diff`, NUMERIC/FLOAT64 arithmetic, `order by` in CTAS and
    the key hashes all ran rather than only compiling. Two caveats that come out of it: the
    surrogate-key *values* still differ between targets by design (NOTES item 1 above), and
    `accepted_values` on a boolean column is a portability trap — dbt renders its literals
    as quoted strings, which BigQuery rejects (`dim_date.is_weekend`, see "Measured against
    the real dataset").
11. **The time-zone handling on the real path.** It assumes DuckDB's `bigquery` extension
    returns TIMESTAMP as TIMESTAMPTZ (SPEC section 2). Only the fixture, which is loaded as
    `timestamptz`, has exercised it.

---

# NOTES — card t_44abf1ef (the transpile macro layer)

Scope: SPEC section 7 (7.1–7.7). The model tree of card 2 is the base; this card moves the
cross-target seam into `macros/polyglot/`, adds the macro families the two dialects differ on,
adds the guardrail that makes "portable" a number, and adds one model (`dim_date`) that makes the
new date macros load-bearing instead of dead code. `profiles.yml`, `dbt_project.yml` and
`packages.yml` are untouched, `main` is untouched, nothing is committed by the agents that wrote
the code.

## Counts

* **28 macros**: 26 dialect macros + 2 `run-operation` macros (`polyglot_render`,
  `polyglot_selfcheck`). 52 branch macros in total (26 × `default__`/`bigquery__` pairs).
* 11 files in `macros/polyglot/`; `analyses/polyglot_showcase.sql`; `scripts/check_portability.py`;
  `scripts/polyglot_check.sh`; `models/marts/dim_date.sql`.
* 29 models (7 staging + 11 intermediate + 11 marts) and 168 tests = **197 build nodes**,
  all successful, twice in a row. `dbt compile --target bigquery` also compiles the analysis:
  `29 models | 168 tests | 1 analysis | 198 success`.
* Nine of the 26 dialect macros are not called by any model in this warehouse yet
  (`decimal_type`, `type_bigint_array`, `safe_cast`, `except_columns`, `struct_literal`,
  `generate_series`, `format_date_str`, `timestamp_trunc_to`, `regexp_contains`). They are not
  untested: the self-check executes their DuckDB branch, the renders show their BigQuery branch,
  and the showcase analysis calls every one of them on every compile.

## Files

Created:

| file | what |
|---|---|
| `macros/polyglot/types.sql` | `int_type`, `string_type`, `float_type`, `timestamp_type`, `money_type`, `decimal_type(p,s)`, `type_bigint_array` |
| `macros/polyglot/casting.sql` | `safe_cast`, `to_string`, `to_utc_timestamp` |
| `macros/polyglot/selection.sql` | `except_columns` |
| `macros/polyglot/structs.sql` | `struct_literal` |
| `macros/polyglot/arrays.sql` | `generate_series`, `generate_date_series`, `unnest_alias` |
| `macros/polyglot/dates.sql` | `date_diff_days`, `format_date_str`, `format_month`, `timestamp_trunc_to`, `day_of_week_iso`, `month_start`, `month_number`, `seconds_between` |
| `macros/polyglot/math.sql` | `safe_divide` |
| `macros/polyglot/strings.sql` | `regexp_contains` |
| `macros/polyglot/keys.sql` | `generate_surrogate_key` |
| `macros/polyglot/self_check.sql` | `polyglot_render(include_bignumeric)`, `polyglot_selfcheck()` |
| `analyses/polyglot_showcase.sql` | one query calling every macro; compiled for both targets, never run |
| `models/marts/dim_date.sql` | the date spine (1415 rows on the fixture), the model that uses the date macros |
| `scripts/check_portability.py` | the guardrail (15 BigQuery-only + 13 DuckDB-only tokens, both directions, plus the target-branch check on `models/` and `tests/`), with `--demo` |
| `scripts/polyglot_check.sh` | `make polyglot`: check-env, fixture, self-check, both renders, the decimal ceiling, the guardrail, the guardrail's `--demo` |

Deleted: `macros/cross_target.sql` (its 10 macros moved into the files above, names and
behaviour unchanged).

Modified: 18 model files and `models/marts/_marts__models.yml` (the `int_type()` refactor,
`safe_divide` in three rates, `dim_date`'s docs and tests), `Makefile` (`polyglot`, `portability`
targets plus help lines), `README.md`, `SPEC.md` (section 5 totals), this file.

## The hardest difference

**The `unnest(...)` alias in `FROM`** — the one place the macro layer had to *grow a helper*
rather than add a branch. `cross join unnest(<array>) as date_day` binds `date_day` to the
element on BigQuery and to the **table** on DuckDB, so on DuckDB `date_day` is a
`STRUCT(unnest DATE)` and `strftime(<struct>, …)` does not resolve; DuckDB needs
`as date_day__unnest(date_day)`, which BigQuery rejects. `unnest` itself stays plain SQL (its name
and semantics really are identical) and only the alias is dispatched, as `unnest_alias`.

The most dangerous to get *wrong* is **`day_of_week_iso`**: BigQuery's `DAYOFWEEK` numbers Sunday
1 (DuckDB's `isodow` is already ISO), and BigQuery has no `%` operator, so the branch is
`(mod(extract(dayofweek from x) + 5, 7) + 1)`. A wrong formula still executes on DuckDB and would
only be caught by reading BigQuery's documentation — there is no way to run it here. Same class of
trap: `FORMAT_DATE` takes the format string **first**, and BigQuery's bare `WEEK` starts on Sunday
where DuckDB's `'week'` is ISO (`week(monday)` is rendered for that case). Three SPEC renderings
were wrong in exactly this way and were corrected during implementation:
`format_date(fmt, expr)` not `format_date(expr, fmt)`, `mod(...)` not `%`, and `week(monday)`.

## Places a macro could not hide the difference

1. **The decimal ceiling.** BIGNUMERIC (76.76 digits) has no DuckDB equivalent; DuckDB DECIMAL
   stops at 38 digits. `decimal_type(p > 38)` is a compiler error on DuckDB and `bignumeric` on
   BigQuery — never a silent `double`.
2. **Date series element type.** BigQuery `GENERATE_DATE_ARRAY` returns `ARRAY<DATE>`; DuckDB's
   date `generate_series` needs an explicit interval and returns `TIMESTAMP[]`, so the DuckDB
   branch casts back to `date[]`.
3. **The FROM alias above** — a relation-level difference, not an expression-level one.
4. **Division typing.** `safe_divide` must be `DOUBLE`/`FLOAT64`. BigQuery's SAFE_DIVIDE returns
   its inputs' type (`NUMERIC` on two `NUMERIC` inputs) and DuckDB keeps `decimal / decimal` as
   DECIMAL, so both branches cast both sides to the float type — that is what makes
   `mart_product_performance.gross_margin_rate` `DOUBLE`/`FLOAT64` rather than `NUMERIC`. So the
   two money metrics that want decimal rounding keep `round(x / nullif(y, 0), 2)` cast to
   `money_type()`. Deliberate, documented in the macro's docstring.
5. **The source database name** (`bigquery-public-data` vs `dev`) belongs to a relation, not an
   expression, so it stays in `models/staging/_thelook__sources.yml` — the single allowlisted
   target read in the whole model tree.
6. **A documented caveat, not solved:** `generate_date_series(…, '1 month')` drifts on DuckDB when
   it starts on a month end (DuckDB adds the interval to the previous element:
   `2024-01-31 → 02-29 → 03-29`). BigQuery is unmeasurable here. `arrays.sql` says to start month
   steps on the 1st.

## Verification (every command run on this machine, 2026-09-26)

| command | result |
|---|---|
| `make duck` ×2 | exit 0 both times, `29 models \| 168 tests`, `197 total \| 197 success` (5.5 s second run) |
| `dbt ls --resource-type model --quiet --target duckdb \| wc -l` | `29` |
| `dbt compile --target bigquery` | exit 0, `29 models \| 168 tests \| 1 analysis` |
| `dbt run-operation polyglot_selfcheck --target duckdb` | exit 0, `selfcheck: all 44 cases ok on duckdb` |
| `dbt run-operation polyglot_render --target bigquery` | exit 0, 31 renderings |
| `dbt run-operation polyglot_render --args '{include_bignumeric: true}' --target bigquery` | exit 0, `render decimal_type bigquery :: bignumeric` |
| … the same with `--target duckdb` | **exit 1** with the ceiling message (expected failure) |
| `python3 scripts/check_portability.py` | exit 0, `PORTABLE`: 30 files, 0/15, 0/13, 0 target branches |
| `python3 scripts/check_portability.py --demo` | exit 0: `NOT PORTABLE: 2 finding(s)` with the demo file, then `PORTABLE` |
| `make portability`, `make polyglot` | exit 0, `polyglot check: all steps ok` |
| my own SQL on `dev.duckdb` | 3 rewritten rates equal the old formula row for row (0 differing rows), mart row counts unchanged (3000/8000/10000/400/200/10/1040/200/400/864 + dim_date 1415), gross revenue still `642483.63`, `dim_date` contiguous and its calendar attributes correct on every row |
| my own adversarial leak (a model with raw `safe_cast`/`timestamp_trunc`/`array<int64>`/`bignumeric`/`float64`/`strftime`) | guardrail exited 1 with 6 findings (5/15 DuckDB-side, 1/13 BigQuery-side), then back to `PORTABLE` when removed |

## What is NOT verified for card 3

1. **Every `bigquery__` branch is rendered, never executed.** 26 of them. Rendering proves the Jinja
   branch was taken and looks like BigQuery syntax; it does not prove BigQuery accepts it. In
   particular the five macros `dim_date` introduced (`generate_date_series`, `day_of_week_iso`,
   `format_date_str`, `date_diff_days`, `unnest_alias`) have never run anywhere except DuckDB.
2. **The guardrail is a blacklist.** It fails on the 15/13 tokens listed in the README; a
   BigQuery-only construct outside that list would pass. It also cannot tell whether the *DuckDB*
   render would run on BigQuery — only that it carries no token it knows about.
3. **`decimal_type`'s BigQuery branch is unexecuted**, so "`numeric` for `(38,9)`" is a rule from
   BigQuery's documentation, not a measurement. A `p = 38, s = 9` value needing all 38 integer
   digits would not fit BigQuery's NUMERIC (38,9 means 29 integer digits + 9 fractional) — the rule
   maps `p <= 38 and s <= 9` to NUMERIC, which is right for the shapes this project casts but is a
   judgement call, not a measured guarantee.
4. **`generate_date_series` month/quarter/year steps** drift on DuckDB from a month-end start
   (measured); BigQuery's behaviour in that case is unmeasured. `make polyglot`'s self-check only
   uses month-start dates.
5. **The self-check's BigQuery half is skipped by design** (`selfcheck skipped: bigquery cannot be
   executed here`), so `make polyglot` on a machine without credentials proves the DuckDB half only.

## Process note (honest)

The macro library, `dim_date`, the guardrail and the shell wrapper were written by Claude Code in
three print-mode runs. The **third run was cut off mid-flight** by Claude Code's weekly subscription
limit (`429 ... You've hit your weekly limit · resets 10am (Europe/Vienna)`; `--fallback-model haiku`
returns the same 429, and no other coding CLI — codex, opencode — is installed on this box). It had
already written `scripts/check_portability.py`, `scripts/polyglot_check.sh` and the `Makefile`
targets, but had not verified them. Bruno therefore verified the guardrail here, including an
**independent adversarial leak** the script's own `--demo` does not use, and wrote the README,
`SPEC.md` and this NOTES section by hand. Costs: run 1 `$2.06` (63 turns), run 2 `$0.88` (29 turns),
run 3 `$1.07` (39 turns, aborted) = **$4.01**.

---

# Card 4 — the parity harness (`scripts/parity.py`)

## What it is

`make parity` runs `scripts/parity.py`. For every model it compares two independently built
legs on: row count, column names, canonical column types, and one order-independent checksum per
column, plus a per-column null count and distinct count. It writes `parity-report.md` and
`parity-report.json` (both gitignored — they are run outputs, attached to the card instead) and
exits 0 / 1 / 2 as documented at the top of the script.

`scripts/parity.sh` (the card-1 row-count stub) is deleted; the Makefile's `parity` target now runs
the Python harness.

## The two legs, and why one of them is read-only

* **DuckDB** — the materialised `dev.duckdb` (schema `main`), read with the `duckdb` CLI. Measured
  only after `make duck` has built it.
* **BigQuery** — the harness first *attempts* the real `dbt build --target bigquery`. On this
  machine that fails, always the same way:

      [error] [DbDriverFailed (dbt1308)]: Database Error in model stg_thelook__events
        [BigQuery] googleapi: Error 404: Not found: Dataset coreychimpbot:experiments_dev
        was not found in location US

  The dataset does not exist (checked read-only, HTTP 404 on `datasets.get`) and this account is
  denied `bigquery.datasets.create` — a direct `datasets.create` call returns
  `403 Access Denied: Project coreychimpbot: User does not have bigquery.datasets.create permission
  in project coreychimpbot`. There is no other dataset in the project to write into. So the
  materialised BigQuery leg cannot run here, and `make bq` still exits non-zero.

  That is a *write* permission. Reading is fine: `jobs.create` is granted and the account can query
  `bigquery-public-data`. So the harness **compiles the DAG with every layer ephemeral** (a throwaway
  project directory whose `models/`, `macros/` and `tests/` are symlinks into the repo, with
  `+materialized: ephemeral` on all three layers), which makes `dbt compile --target bigquery`
  emit each model as one self-contained `SELECT` with its whole DAG inlined as
  `__dbt__cte__…` CTEs. Those run as plain queries: no dataset, no `CREATE TABLE`, no write
  permission. Every one of the 29 models executes on the real BigQuery engine and returns real rows.

  What that does and does not prove is written up in the README > "What is NOT verified": the model
  tree's BigQuery side is now *executed*, but never *materialised*.

## The checksum, and why it is not either engine's native hash

`hash()` (DuckDB) and `FARM_FINGERPRINT()` (BigQuery) are different algorithms, so their values
could never be compared across engines. Instead both engines render the value to a canonical text
and hash it the same way:

```sql
-- DuckDB
CAST(('0x' || substr(md5(<canonical text>), 1, 8)) AS BIGINT)
-- BigQuery
CAST(CONCAT('0x', SUBSTR(TO_HEX(MD5(<canonical text>)), 1, 8)) AS INT64)
```

and `SUM` those per row (SUM, not XOR: a duplicated row must change the answer; 8 hex digits = 32
bits, so 2^31 rows cannot overflow a signed 64-bit sum).

**The portability of that construction is measured, not assumed.** `--self-check` runs both
engines' spelling over a fixture of constants (int, float, bool, date, timestamp, string, decimal)
before any model is measured, and refuses to measure anything if they disagree. Measured
2026-09-27, identical on both engines:

    int_sum 6659028165  float_sum 4313495136  bool_sum 4760141636  date_sum 4221762807
    ts_sum  4568127435  str_sum   4835053162  dec_sum  4732242430  f_distinct 2

## The traps, each as a decision

| trap | decision |
|---|---|
| BIGNUMERIC arrives as VARCHAR | canonical types read `bignumeric` vs `string`; raw types recorded; nothing widened |
| NUMERIC(38,9) rounds at 38 digits | types compared by *kind*, not precision (DuckDB `DECIMAL(18,2)` vs BigQuery `NUMERIC`); both raw strings always in the JSON |
| floating point | integer micro-units: `CAST(ROUND(x * 1000000) AS BIGINT)`, one rule both engines; no tolerance |
| TIMESTAMP vs TIMESTAMPTZ | compared as **instants**: `epoch_us` vs `UNIX_MICROS`, microseconds since the epoch UTC |
| arrays / structs / JSON | structural: arrays sorted and `|`-joined, structs rendered field by field recursively; never raw JSON |
| NULLS ordering / row order | nothing depends on row order: every metric is an aggregate, the one sort is inside an array's own values, identical on both engines |
| NULLs | SUM skips NULLs, so every column also carries an explicit null count and a distinct count |

When card 4 ran, no model had an array, struct or JSON column, so those branches of the
renderer were implemented but unexercised. **Since card t_68bfec9c** the rendering is exercised:
`mart_polyglot_types` has one column of each kind (`int_array`, `date_array`, `pair_struct`,
`pair_json`), built on both targets from the macro layer, and its renderings are asserted by the
self-check (`polyglot_selfcheck`, DuckDB values and types) and by the guardrail
(`check_portability.py`'s type-coverage check, both renders). Still not proven: cross-engine
**value** parity of those columns, which needs the same input rows and the credentialed BigQuery
leg (see the card t_68bfec9c section at the end of this file).

## What the run found

`make parity`, 2026-09-27, exit **1**:

* **Digest self-check: PASS.** **DuckDB-vs-DuckDB baseline: MATCH** (`dev.duckdb` rebuilt from
  scratch and re-measured; every model reproduced exactly).
* **All 29 models measured on both legs.** No model went unmeasured.
* **One gating mismatch — a real defect, not a source-data difference.**
  `mart_product_performance.gross_margin_rate` was `DOUBLE` on DuckDB and `NUMERIC` on BigQuery.
  Cause: `bigquery__safe_divide` renders BigQuery's `SAFE_DIVIDE(<a>, <b>)` on the inputs' own
  types, and `SAFE_DIVIDE` returns the input type — on two `NUMERIC` inputs that is `NUMERIC`,
  while the `default__safe_divide` branch casts both sides to float. The macro's docstring says it
  is float-typed on purpose, so the BigQuery branch is not doing what it says. The other two
  callers (`int_products__returns.return_rate`, `mart_cohort_retention.retention_rate`) are safe:
  their inputs are integers, so `SAFE_DIVIDE` yields `FLOAT64` and the canonical types agree.
  Not fixed in card 4 — it is the macro layer's, and fixing it there would have hidden the finding.
  **Fixed in card 7** with the one-line change: `bigquery__safe_divide` now casts both sides to
  `float_type()` before `SAFE_DIVIDE`, so this gating mismatch is gone.
* **28 of the 29 models differ on rows/values**, because the two legs read different data: 3,000
  fixture orders vs 124,952 real, 20,000 fixture events vs 2,425,698 real, and so on. Those
  checksums are reported, not gated, until both legs read one dataset; `--same-data` promotes
  them to gating for that (cards 5/6).
* **One model matches on everything, values included**: `stg_thelook__distribution_centers` — the
  fixture copies the real ten centres verbatim. That is the positive control: it shows the
  checksums compare data rather than always answering "differs".

## Commands run (real output)

    $ make parity                      # 2026-09-27, BQ_KEYFILE=<sa key>, exit 1
    [1/5] make duck  (fixtures + dbt build --target duckdb)
          29 models discovered
    [2/5] digest self-check: PASS
    [3/5] dbt build --target bigquery (attempt)
          dataset coreychimpbot.experiments_dev: HTTP 404 Not found
          exit 1
    [3/5] compiling the DAG read-only for BigQuery (all layers ephemeral)
    [4/5] measuring every model on both legs
    [5/5] DuckDB baseline: rebuild and prove the measurements reproduce
          baseline: MATCH
    parity: MISMATCH. gating: ['mart_product_performance']; value/row: [27 others]

    $ python3 scripts/parity.py --skip-build --no-baseline    # no BQ_KEYFILE set, exit 2
    [2/5] BigQuery leg unavailable: no service-account key (set BQ_KEYFILE) or no openssl
    parity: BigQuery leg could not be measured. Parity is NOT established.

    $ make portability   # unchanged, still green: 30 compiled files, 0/15, 0/13, 0 findings
    $ make polyglot      # unchanged, still green: all steps ok

## What is NOT verified for card 4

1. **The materialised BigQuery build has still never run.** Read-only execution proves the SQL is
   accepted and returns rows; it does not prove `CREATE TABLE` DDL, partitioning/clustering,
   `maximum_bytes_billed` enforcement (no query came close to the 1 GB ceiling), or anything about
   the dataset's real existence. `make bq` remains broken on this machine for a permission reason
   outside the project.
2. **The array/struct/JSON rendering was unexercised** when card 4 ran — no model had such a
   column. *Updated by card t_68bfec9c:* `mart_polyglot_types` now renders all three on both
   targets, the self-check asserts the DuckDB values and types, and the guardrail asserts each
   construct is present in each render. What is still not proven is cross-engine **value** parity
   of those columns: that needs the same input rows and the credentialed BigQuery leg.
3. **Cross-engine *value* parity is still not established**, and cannot be until both legs read one
   dataset — that is cards 5/6. What is established is schema parity (with one named exception) and
   the machinery, verified end to end, that will measure value parity the day the data is shared.
4. **The BigQuery leg needs `openssl`** (stdlib + CLI; no google-* python packages are installed on
   this box). Without it, or without `BQ_KEYFILE`, the leg is reported unavailable and the run
   exits 2 rather than pretending.
5. **The harness writes nothing** to BigQuery. It cannot create the dataset it would need, so it
   never tried to.

# Card t_33ffc523 — the pre-PR gate (`scripts/pre_pr.sh`, `make pre-pr`)

## What it is

One command for the whole pre-PR routine, in this order: `scripts/check_env.sh`,
`scripts/load_duckdb_sources.sh`, `scripts/check_portability.py`, `scripts/parity.py`. It reports
each step `ok` / `FAIL` in the `scripts/polyglot_check.sh` style and, like it, has no `set -e`, so a
failed step still reports on the later ones. The last line is the wall time, `pre-pr: <N.N>s`.

Why: nothing routinely ran the guardrail. A raw `try_cast(...)` or a `target.type` branch in a
model passes `make duck`; without credentials `make parity` then exits 2 ("NOT established"),
which reads like "skipped"; with credentials a target branch passes parity, because both branches
are valid SQL. Only the guardrail catches either.

**The fixture step is required, and is not in the card's original sketch.** `check_portability.py`
refuses to run without `dev.duckdb` (exit 2, `dev.duckdb not found: run make fixtures first`), so
`load_duckdb_sources.sh` runs unconditionally before it (about half a second). `make duck` is not
called: `parity.py` already runs it, plus a DuckDB baseline rebuild. For the same reason the
`pre-pr` make target has no prerequisites.

## The exit-code contract (`bash scripts/pre_pr.sh`)

| exit | meaning |
|---|---|
| 0 | every step `ok`, parity established on both targets |
| 1 | a real finding: any step failed. Wins over 2 when both happen |
| 2 | every other step `ok`, but `parity.py` exited 2 (no `BQ_KEYFILE`): the step is reported `n/a`, not `FAIL`, and the script prints `PARITY NOT ESTABLISHED (no BQ_KEYFILE)`, matching `run_bq.sh` / `parity.py` |

**Through make the distinction is only in the text.** GNU make exits 2 for *any* failed recipe, so
`make pre-pr` exits 2 on a real finding too; the script's status survives as make's
`make: *** [Makefile:..: pre-pr] Error 1` (finding) vs `Error 2` (not established) line, and in the
summary lines above it. Run `bash scripts/pre_pr.sh` when a caller branches on the exit status.

With `BQ_KEYFILE` set the parity step queries BigQuery read-only, each job capped at 1 GB billed.

## Verification (this machine, 2026-09-27)

    $ bash scripts/check_env.sh                                              # exit 0, 7 ok
    $ env -u BQ_KEYFILE -u GOOGLE_APPLICATION_CREDENTIALS make pre-pr        # make exit 2 ("Error 2")
      ok    bash scripts/check_env.sh
      ok    bash scripts/load_duckdb_sources.sh
      ok    python3 scripts/check_portability.py      (30 files, 0/15, 0/13, 0 findings, PORTABLE)
      n/a   python3 scripts/parity.py (exit 2: parity NOT established, no BQ_KEYFILE)
    PARITY NOT ESTABLISHED (no BQ_KEYFILE)
    pre-pr: 24.0s

    # regression probe: `try_cast(1 as int) as regression_probe` added to the SELECT list of
    # models/staging/stg_thelook__orders.sql
    $ env -u BQ_KEYFILE bash scripts/pre_pr.sh                               # exit 1
      FAIL  python3 scripts/check_portability.py (exit 1)   (DuckDB-only tokens in the BigQuery render: 1/13)
      n/a   python3 scripts/parity.py (exit 2: ...)
    pre-pr: 1 step(s) FAILED
    pre-pr: 24.2s
    $ env -u BQ_KEYFILE make pre-pr                                          # "Error 1", make exit 2
    $ git checkout -- models/                                                # reverted; git status clean
                                                                             # apart from this card's files

    # the credentialed leg, run by the orchestrator
    $ export BQ_KEYFILE=/home/hermes/.config/gcp/coreychimpbot-sa.json   # the box's service-account key
    $ bash scripts/pre_pr.sh                                             # exit 0, 67 s wall (date +%s, external measure)
      ok    bash scripts/check_env.sh
      ok    bash scripts/load_duckdb_sources.sh
      ok    python3 scripts/check_portability.py    (30 files, 0/15, 0/13, 0 findings, PORTABLE)
      ok    python3 scripts/parity.py               ('[3/5] compiling the DAG read-only for BigQuery (all layers ephemeral)', baseline MATCH, schema parity holds on all 29 models)
    pre-pr: all steps ok
    pre-pr: 67.0s

**Measured wall time: 24.0 s without credentials (exit 2), 67 s with them (exit 0).** Without
`BQ_KEYFILE`: `make pre-pr`, exit 2; 24.2 s for the direct script run with the probe; almost all of
it is `parity.py`'s DuckDB build and baseline rebuild. With `BQ_KEYFILE`: `bash scripts/pre_pr.sh`,
exit 0, 67 s by an external `date +%s` measure (the script's own line said 67.0 s). The extra ~43 s
is the read-only BigQuery leg.

`shellcheck` is not installed on this machine, so `scripts/pre_pr.sh` was not shellchecked; nothing
was installed to do it.

# Card t_68bfec9c — exercise the array, struct and JSON rendering on both targets

## What it is

Card 4 left a whole class of SQL claimed but never shown on a real column: no model had an array,
struct or JSON column, so `parity.py`'s array/struct/JSON branches of `Engine.canon`, and the
macros behind them, ran only inside the self-check (and JSON not even there). This card closes the
*rendering* half of that gap. It is a coverage card, not a feature: no macro was added or changed.

* **`models/marts/mart_polyglot_types.sql`** — one constant row, five columns, built only from
  existing macros (SPEC 7.2) plus `to_json(...)`. Documented in `_marts__models.yml` (`not_null`
  on `id` only). The values are constants, not business data. The tree is now 30 models.
* **`polyglot_selfcheck`** — three new cases: the `generate_date_series` value, the `to_json` of a
  `struct_literal` as VARCHAR, and its `typeof`. 44 → 47 cases.
* **`check_portability.py`** — a *positive* check (`scan_type_coverage`, `TYPE_SHOWCASE_MODEL`,
  `TYPE_COVERAGE`). The token lists only prove the other dialect is *absent*; a macro that silently
  dropped its construct would still have passed. Now each render of `mart_polyglot_types` must
  contain every required substring (comments stripped first, so the model's header comment that
  mentions `to_json(...)` cannot satisfy it). A missing file or substring is a finding in the same
  `findings` list, so it prints `NOT PORTABLE` and exits 1. One new summary line:
  `type coverage (mart_polyglot_types): ...`.

| target | required substrings |
|---|---|
| duckdb | `generate_series(`, `date[]`, `'id':`, `'channel':`, `to_json(` |
| bigquery | `generate_array(`, `generate_date_array(`, `struct(`, `to_json(` |

## Decision: `to_json(...)` is not a macro

Same precedent as `unnest(...)` (`macros/polyglot/arrays.sql`): the function name is the same on
both engines and it returns the JSON type on both, so a wrapper would only hide plain SQL. What
*does* differ — the struct literal inside it — already goes through `struct_literal()`.

## The renderings, per column (from the compiled trees in `target/portability/<target>/`)

| column | DuckDB render | BigQuery render |
|---|---|---|
| `id` | `cast(1 as bigint)` | `cast(1 as int64)` |
| `int_array` | `generate_series(1, 3)` | `generate_array(1, 3)` |
| `date_array` | `cast(generate_series(date '2024-03-01', date '2024-03-03', interval 1 day) as date[])` | `generate_date_array(date '2024-03-01', date '2024-03-03', interval 1 day)` |
| `pair_struct` | `{'id': 1, 'channel': 'web'}` | `struct(1 as id, 'web' as channel)` |
| `pair_json` | `to_json({'id': 1, 'channel': 'web'})` | `to_json(struct(1 as id, 'web' as channel))` |

The materialised DuckDB row (`select *, typeof(...) from main.mart_polyglot_types` on `dev.duckdb`
after `make duck`):

| column | value | DuckDB type |
|---|---|---|
| `id` | `1` | `BIGINT` |
| `int_array` | `[1, 2, 3]` | `BIGINT[]` |
| `date_array` | `[2024-03-01, 2024-03-02, 2024-03-03]` | `DATE[]` |
| `pair_struct` | `{'id': 1, 'channel': web}` | `STRUCT(id INTEGER, channel VARCHAR)` |
| `pair_json` | `{"id":1,"channel":"web"}` | `JSON` |

No rendering had to be left divergent: every column renders on both targets from the same model
text, with no target branch.

## Commands run (real output, this machine, 2026-10-06)

    $ make duck
    Finished 'build' with 1 warning for target 'duckdb' [6.1s]
    Processed: 30 models | 168 tests
    Summary: 198 total | 198 success

    $ make polyglot
    ... (dbt.log) selfcheck ok  generate_date_series value
    ... (dbt.log) selfcheck ok  to_json(struct_literal) value
    ... (dbt.log) selfcheck ok  to_json(struct_literal) typeof
    ... (dbt.log) selfcheck: all 47 cases ok on duckdb
      ok    .venv/bin/dbt run-operation polyglot_selfcheck --target duckdb
      ok    .venv/bin/dbt run-operation polyglot_render --target duckdb        (31 render lines)
      ok    .venv/bin/dbt run-operation polyglot_render --target bigquery      (31 render lines)
      ok    ... --args {include_bignumeric: true} --target duckdb (failed as expected with the decimal-ceiling message)
      ok    python3 scripts/check_portability.py
      ok    python3 scripts/check_portability.py --demo
    polyglot check: all steps ok

    $ make portability
    compiled files checked: 31 (models: 30, analyses: 1)
    BigQuery-only tokens in the DuckDB render: 0/15
    DuckDB-only tokens in the BigQuery render: 0/13
    target-branch findings: 0
    type coverage (mart_polyglot_types): array/struct/json present in both renders
    PORTABLE

    $ python3 scripts/check_portability.py --demo
    demo: wrote models/intermediate/_portability_demo.sql (raw regexp_contains + a target.type branch)
    type coverage (mart_polyglot_types): array/struct/json present in the duckdb render
    NOT PORTABLE: 2 finding(s)
    demo: guardrail failed as designed (1 dialect finding(s), 1 target-branch finding(s) in _portability_demo.sql)
    demo: removed models/intermediate/_portability_demo.sql
    type coverage (mart_polyglot_types): array/struct/json present in both renders
    PORTABLE
    demo: the guardrail failed as designed, then passed again

    # probe, reverted: pair_json replaced by `cast(null as {{ string_type() }}) as pair_json`
    $ python3 scripts/check_portability.py                                      # exit 1
    target/portability/duckdb/compiled/bq_duckdb_experiments/models/marts/mart_polyglot_types.sql: required 'to_json(' missing - the duckdb render of mart_polyglot_types dropped an array/struct/json construct
    target/portability/bigquery/compiled/bq_duckdb_experiments/models/marts/mart_polyglot_types.sql: required 'to_json(' missing - the bigquery render of mart_polyglot_types dropped an array/struct/json construct
    type coverage (mart_polyglot_types): 2 finding(s)
    NOT PORTABLE: 2 finding(s)

The `1 warning` in every dbt run is the existing `MacroSyntaxInvalid (dbt1502)` on
`analyses/value_parity/rows.md:79:6`, a committed file this card did not touch.

## What is NOT verified for card t_68bfec9c

Status after the orchestrator re-ran the gate with a BigQuery credential on 2026-10-07 (evidence in
the section at the end of this file). Items 1, 2 and 4 were open when this list was first written;
they are settled as noted below. Items 3 and 5 stand.

1. ~~**The BigQuery render is compiled, never executed.**~~ **Settled.** `make bq` built all 30
   models on BigQuery (198 tests, 197 success, 1 intended warn); `mart_polyglot_types`
   materialised there with a `JSON` column and passed its `not_null` test, and `parity.py` then
   measured the model by running its compiled SQL read-only on BigQuery. `generate_array`,
   `generate_date_array`, `struct(...)` and `to_json(...)` really ran on the engine.
2. ~~**Cross-engine value parity of these columns is not established.**~~ **Partly settled, and what
   is left is a named divergence.** The canonical schema of all five columns agrees across the
   engines, and four of the five column checksums agree exactly; the fifth, `pair_json`, differs
   because the two engines serialise a JSON value with different key order. Exact digests are in
   the section at the end. A `--same-data` run would therefore flag this one column, for that
   reason alone — semantically the two JSON values are the same.
3. **Struct field types differ by width, and the canonical comparison absorbs it.** DuckDB types
   the literal `1` inside the struct as `INTEGER` (`STRUCT(id INTEGER, channel VARCHAR)`, measured
   above); BigQuery's is `INT64` (`STRUCT<id INTEGER, channel STRING>`). Both canonicalise to
   `struct<id:int64,channel:string>` in `parity.py` (`bq_kind`/`duck_kind`), which is why the schema
   check holds on this model; nothing pins that mapping with a test, so a future type rename could
   pass unnoticed.
4. ~~**The JSON text on BigQuery is not measured.**~~ **Settled: it is measured, and it differs by
   key order.** DuckDB `to_json({'id': 1, 'channel': 'web'})` renders `{"id":1,"channel":"web"}`;
   BigQuery's `TO_JSON(struct(1 as id, 'web' as channel))` stores the same object, but reading it
   back the way `parity.py`'s BigQuery JSON branch does — `TO_JSON_STRING(pair_json)` — re-serialises
   it as `{"channel":"web","id":1}`. Key order is not part of JSON object equality, so this is a
   comparison artefact rather than an engine disagreement about content; but the harness compares
   canonicalised *text*, so it sees a difference. `CAST(pair_json AS STRING)` is not available on
   BigQuery (`Invalid cast from JSON to STRING`), so there is no raw-text accessor to fall back on.
5. `scripts/row_join.py` gates on `>= 29` / `< 29` relations; with 30 models that still holds, but
   that script was not run here (it needs the pair build `make value-parity` writes). It shared the
   stdout-parsing fragility described below and now uses the same helper as `parity.py`.

## Verified end to end with the credentialed leg (orchestrator, 2026-10-07)

Everything above this section was written from the DuckDB leg alone: `BQ_KEYFILE` was unset, so the
BigQuery side was compile-only. That is no longer the state. A service-account credential for the
project `profiles.yml` names (`coreychimpbot`) was used to run the credentialed parts of the gate,
which settles two of the open items above and turns a third into a named, reproducible divergence.

### The BigQuery render executes

    $ make bq                                      # 30 models, 168 tests
    Finished 'build' with 2 warnings for target 'bigquery' [2m 29s]
    Processed: 30 models | 168 tests
    Summary: 198 total | 197 success | 1 warn

The `warn` is `assert_order_item_created_at_is_plausible`, a `severity: warn` test that fires on the
real dataset rather than on the fixture (`dbt test --select
assert_order_item_created_at_is_plausible --target bigquery` -> `Warned test
assert_order_item_created_at_is_plausible [1 of 1 in 2.87s]`). The other warning is the committed
`analyses/value_parity/rows.md:79:6` syntax note that every run carries. `mart_polyglot_types`
materialised on BigQuery and its `not_null_mart_polyglot_types_id` test passed there.

### A real harness defect, found by the first array column in the tree

`python3 scripts/parity.py` could not measure the new model at all:

    $ make pre-pr                                  # BQ_KEYFILE set, before the fix
    $ python3 scripts/parity.py
    ...
    pre-pr: 1 step(s) FAILED

    File "scripts/parity.py", line 364, in sql
        return json.loads(out.stdout)
    json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)

`DuckLeg.sql()` parsed the DuckDB CLI's stdout as JSON. `Engine.canon`'s array branch is the first
measured query in the tree to use a DuckDB lambda (`list_transform(<col>, x -> CAST(x AS VARCHAR))`),
and DuckDB 1.5.5 — the version this repo pins and `check_env.sh` enforces — prints a **deprecation
WARNING to stdout, ANSI-coloured, before the JSON**:

    "\x1b[90mWARNING:\n\x1b[00m\x1b[90mDeprecated lambda arrow (->) detected. ...\x1b[00m\n\n[{\"__rows\":1,...

So no model without an array column could ever have hit it: 29 of the 30 measured fine, and the only
one that did not is the one this card added. Fixed in `scripts/parity.py` with a `last_json()` helper
(tries each `[` / `{` as a document start, returns the last document that parses, and falls back to
`json.loads(text)` so a genuinely bad stdout still raises `JSONDecodeError` as before), and
`scripts/row_join.py`'s `ddb()` — which had the same fragility and meets the same warning through
`parity.metrics_sql` — now calls the same helper. The numbers the two legs produce are unchanged:
`mart_polyglot_types` on DuckDB still measures `id__sum` 3301589560 and `pair_json__sum` 2782575947,
the values read straight out of the raw CLI output before the change.

### The gate, with the credentialed leg

    $ make pre-pr                                  # BQ_KEYFILE set, after the fix
    $ bash scripts/check_env.sh                ... ok
    $ bash scripts/load_duckdb_sources.sh      ... ok
    $ python3 scripts/check_portability.py
        compiled files checked: 31 (models: 30, analyses: 1)
        BigQuery-only tokens in the DuckDB render: 0/15
        DuckDB-only tokens in the BigQuery render: 0/13
        target-branch findings: 0
        type coverage (mart_polyglot_types): array/struct/json present in both renders
        PORTABLE
                                               ... ok
    $ python3 scripts/parity.py
        [4/5] measuring every model on both legs
        [5/5] DuckDB baseline: rebuild and prove the measurements reproduce
              baseline: MATCH
        parity: schema parity holds on all 30 models. Row counts and checksums differ on 29 of
        them, as expected: the two legs read different source data (fixture vs the real dataset).
        That is cards 5/6's job; run with --same-data once both legs read one dataset.
                                               ... ok
    pre-pr: all steps ok
    pre-pr: 300.3s

This is also the first run in which `parity.py`'s array, struct and JSON branches of `Engine.canon`
have run against a real model column on a real engine, which is what the docstring at the top of
that file describes. "Schema parity holds on all 30 models" includes `mart_polyglot_types`: the
canonical kinds of its five columns are identical on both legs.

### The one divergence, named: JSON key order

`target/parity-duckdb-leg.json` and `target/parity-bigquery-leg.json` from that run, for
`mart_polyglot_types` (the `__sum` is the first 8 hex digits of an md5 of the canonicalised text):

| column | DuckDB canonical text | BigQuery canonical text | DuckDB `__sum` | BigQuery `__sum` |
|---|---|---|---|---|
| `id` | `1` | `1` | 3301589560 | 3301589560 |
| `int_array` | `1\|2\|3` | `1\|2\|3` | 45166227 | 45166227 |
| `date_array` | `2024-03-01\|2024-03-02\|2024-03-03` | same | 236720013 | 236720013 |
| `pair_struct` | `1\|web` | `1\|web` | 4205254971 | 4205254971 |
| `pair_json` | `{"id":1,"channel":"web"}` | `{"channel":"web","id":1}` | 2782575947 | 2377532824 |

Measured directly, not inferred:

    $ duckdb dev.duckdb -c "select cast(pair_json as varchar) from main.mart_polyglot_types"
    {"id":1,"channel":"web"}                       # md5 a5dabd4b16ee0be82e20821ce173827f

    # BigQuery, the materialised table make bq wrote
    select to_json_string(pair_json)  from `coreychimpbot`.experiments_dev.mart_polyglot_types
    {"channel":"web","id":1}                       # md5 8db6459844df8ecdda3e96d008395125
    select to_json_string(pair_struct) from ...    {"id":1,"channel":"web"}     # field order kept

So BigQuery's `TO_JSON(struct(...))` stores the object in field order (`id`, `channel`) exactly as
the model text says; it is the **re-serialisation** of an already-`JSON`-typed value through
`TO_JSON_STRING` — the canon `Engine.canon` uses for the `json` kind on BigQuery — that comes back
keyed alphabetically. DuckDB's canon (`CAST(json AS VARCHAR)`) reproduces the stored text. Nothing
about the content differs, and neither engine is wrong; the harness compares text, so it sees two
values. Making the JSON branch engine-independent would need a canonical form both engines can
produce (a key-sorted serialisation, or a structural comparison), which neither engine exposes
through a portable function today — so this stays a named divergence rather than a fix.

One consequence worth carrying forward: a `--same-data` run (`make value-parity`) over a model with
a JSON column will report that column as differing for this reason alone. `mart_polyglot_types` is
the only such model today, and its one row is constant, so the report can be read with that in mind.

# Card t_fc6d405f — the materialised BigQuery build, and what to grant when it cannot run

**The card's premise no longer reproduces.** It assumed `make bq` still fails for a missing
permission. That *was* true before the service account's grants landed; the error then was

    403 Access Denied: Project coreychimpbot: User does not have bigquery.datasets.create permission in project coreychimpbot

It is not true today. Nothing below invents a failure: every "missing permission" the new code can
print is either BigQuery's own 403 message quoted at run time, or (for a dataset that does not
exist and `--create` was not passed) labelled `untested`.

## Measured 2026-10-06 (by the orchestrator; read-only where it matters)

* `coreychimpbot.experiments_dev` exists (created 2026-09-27 09:23:52Z, location `US`), and the
  service account `coreychimpbot@coreychimpbot.iam.gserviceaccount.com` is a dataset `OWNER`.
* `bigquery.datasets.create` is held: a throwaway `datasets.insert` returned HTTP 200 and the
  dataset was deleted again.
* `BQ_KEYFILE=/home/hermes/.config/gcp/coreychimpbot-sa.json bash scripts/run_bq.sh` exits 0:
  `Processed: 29 models | 167 tests` / `Summary: 196 total | 195 success | 1 warn`.
* `maximum_bytes_billed` enforcement, reproduced for the first time with a 1000-byte ceiling:

      HTTP 400 ... {"reason": "bytesBilledLimitExceeded", "message": "Query exceeded limit for bytes billed: 1000. 141557760 or higher required."}

  A job refused this way bills nothing.

The price of one `make bq`:

| measure | bytes | GB |
|---|---:|---:|
| processed, whole build | 1,323,806,504 | 1.3238 |
| billed, whole build (the 10 MB per-query minimum dominates 167 tiny test jobs) | 4,653,580,288 | 4.6536 |
| largest single job, processed | 150,593,696 | 0.1506 |
| ceiling, per job (`maximum_bytes_billed`) | 1,000,000,000 | 1.0000 |
| jobs of the build that come near the ceiling | **0** | |

## What was built

* **`scripts/bq_preflight.py`** (new; stdlib plus the `openssl` CLI, token from
  `scripts/parity.py`'s `access_token()` loaded with `importlib`, as `bq_table_meta.py` does).
  Target from the profile's convention: `BQ_PROJECT` (default `coreychimpbot`),
  `experiments_<DBT_ENV>` (default `dev`), overridable with `--project` / `--dataset`. Key from
  `BQ_KEYFILE`, else `GOOGLE_APPLICATION_CREDENTIALS` when that is a service-account JSON. Only
  `client_email` is printed. Checks, in order: token; `datasets.get` (location, creation time,
  OWNER); `jobs.query` `SELECT 1` (proves `bigquery.jobs.create`, 0 bytes, billed 0); `tables.list`
  when the dataset exists. `--create` attempts `datasets.insert` (location `US`) once, only when
  the dataset is missing. On any blocker it prints a "what to grant" block: two
  `gcloud projects add-iam-policy-binding` commands (`roles/bigquery.jobUser`,
  `roles/bigquery.dataEditor`) built from the key's `client_email`, and the console route
  (`gcloud` is not installed on this box).
* **`scripts/run_bq.sh`**: before `exec`ing dbt, with a key file in play (not gcloud ADC), runs
  `python3 scripts/bq_preflight.py --create`, its output passing straight through. Exit 2 from the
  preflight ends the wrapper with exit 2 and no build; exit 1 (preflight unavailable) falls
  through to dbt as before, as the preflight's contract asks; exit 0 builds. ADC: one line saying
  the preflight was skipped. `BQ_NO_PREFLIGHT=1` skips it.
* `Makefile` (one `help` line), `README.md` (repository map, the `make bq` bullet),
  `docs/gaps.md` section 2.

The preflight's exit-code contract (neither 1 nor 2 is a build failure; no build was started):

| exit | meaning |
|---|---|
| 0 | ready: the dataset exists, a job can be created, the dataset is readable |
| 1 | **preflight unavailable**: no service-account key, no `openssl`, bad credentials, network, an unexpected HTTP status. Nothing is known about the target; the caller falls through to dbt |
| 2 | **named blocker**: the dataset is missing and was not (or could not be) created, a job cannot be created, or the dataset cannot be read. The diagnosis, BigQuery's message and the "what to grant" block are printed |

## Commands run (this worktree, 2026-10-06) and their output

    $ python3 scripts/bq_preflight.py                                        # exit 0
    bigquery preflight: target coreychimpbot.experiments_dev (location US)
      ok    access token obtained for coreychimpbot@coreychimpbot.iam.gserviceaccount.com
      ok    dataset coreychimpbot.experiments_dev exists: location US, created 2026-09-27 09:23:52Z, OWNER projectOwners, coreychimpbot@coreychimpbot.iam.gserviceaccount.com
      ok    jobs.query SELECT 1 ran (bigquery.jobs.create held; processed 0 bytes, billed 0)
      ok    tables.list on coreychimpbot.experiments_dev: 29 relation(s), the dataset is readable
    ready: coreychimpbot.experiments_dev exists, a job can be created and the dataset is readable

    $ python3 scripts/bq_preflight.py --create                               # exit 0, identical
                                                                             # output: nothing to create

    $ python3 scripts/bq_preflight.py --dataset experiments_does_not_exist   # exit 2
    bigquery preflight: target coreychimpbot.experiments_does_not_exist (location US)
      ok    access token obtained for coreychimpbot@coreychimpbot.iam.gserviceaccount.com
      FAIL  dataset coreychimpbot.experiments_does_not_exist not found (HTTP 404 reason=notFound: "Not found: Dataset coreychimpbot:experiments_does_not_exist")
      FAIL  creating it needs bigquery.datasets.create; not attempted. Re-run with --create, or create it in the console (id experiments_does_not_exist, location US)
      ok    jobs.query SELECT 1 ran (bigquery.jobs.create held; processed 0 bytes, billed 0)

    NAMED BLOCKER: coreychimpbot.experiments_does_not_exist cannot be built by coreychimpbot@coreychimpbot.iam.gserviceaccount.com; needed: bigquery.datasets.create (untested: --create was not passed). No build was started.

    what to grant (to coreychimpbot@coreychimpbot.iam.gserviceaccount.com):
      # roles/bigquery.jobUser supplies bigquery.jobs.create
      gcloud projects add-iam-policy-binding coreychimpbot --member=serviceAccount:coreychimpbot@coreychimpbot.iam.gserviceaccount.com --role=roles/bigquery.jobUser
      # roles/bigquery.dataEditor supplies bigquery.datasets.create, and inside the dataset
      # bigquery.tables.create / .updateData / .get and bigquery.datasets.get / .update
      gcloud projects add-iam-policy-binding coreychimpbot --member=serviceAccount:coreychimpbot@coreychimpbot.iam.gserviceaccount.com --role=roles/bigquery.dataEditor
    gcloud is not installed on this box; the console route is BigQuery -> Create dataset
    (id experiments_does_not_exist, location US), plus IAM -> grant the two roles above to coreychimpbot@coreychimpbot.iam.gserviceaccount.com.

    # run as a python3 subprocess with BQ_KEYFILE=/nonexistent in its environment
    $ BQ_KEYFILE=/nonexistent python3 scripts/bq_preflight.py                # exit 1
    bigquery preflight: target coreychimpbot.experiments_dev (location US)
      FAIL  no service-account key: set BQ_KEYFILE (or GOOGLE_APPLICATION_CREDENTIALS to a service-account JSON). Preflight unavailable.

The wrapper's branches were exercised on a scratch copy of `scripts/run_bq.sh` under `target/`,
with a stub `dbt` and a stub preflight that exits 0, 1 or 2 (no BigQuery call; scratch removed):

    preflight 0 -> STUB dbt build --target bigquery --select x; wrapper exit 0
    preflight 1 -> [bq] preflight unavailable (exit 1); building anyway, ...; STUB dbt ...; exit 0
    preflight 2 -> [bq] preflight named a blocker (exit 2): no build was started.; wrapper exit 2
    BQ_NO_PREFLIGHT=1 -> [bq] BQ_NO_PREFLIGHT=1: skipping scripts/bq_preflight.py; STUB dbt ...; exit 0

`bash scripts/run_bq.sh` / `make bq` itself was **not** run by this card (it starts a billable
build); the orchestrator runs it.

The pre-PR gate, which never reaches the preflight or the wrapper:

    $ BQ_KEYFILE=/home/hermes/.config/gcp/coreychimpbot-sa.json bash scripts/pre_pr.sh   # exit 0
      ok    bash scripts/check_env.sh
      ok    bash scripts/load_duckdb_sources.sh
      ok    python3 scripts/check_portability.py    (30 files, 0/15, 0/13, 0 findings, PORTABLE)
      ok    python3 scripts/parity.py               (baseline: MATCH; schema parity holds on all 29 models)
    pre-pr: all steps ok
    pre-pr: 210.1s

## What this does not establish

* **The 403 branches have never run.** This account holds every permission the preflight checks,
  so the `datasets.insert`, `jobs.query`, `tables.list` and `datasets.get` refusal paths, and the
  "missing permission is ..." lines they print, are unexercised. Only the missing-dataset path
  (404, `--create` not passed) ran.
* **`--create` has never created a dataset.** The target exists, and a run that would create
  `experiments_does_not_exist` was not allowed. The insert body is the documented minimum
  (`datasetReference`, `location`); the orchestrator's throwaway insert of 2026-10-06 was a
  separate call, not this code.
* **The two roles are from BigQuery's documented role contents**, not a measurement of a fresh
  principal granted exactly those two and nothing else. The account today holds more (it is a
  dataset OWNER, and project owners are listed too).
* **gcloud ADC is not covered**: the preflight checks service-account keys only.
* **The price is one build on one day.** Billed bytes depend on the number of jobs (10 MB
  minimum each) far more than on data size; a larger source would change processed bytes, and the
  ceiling is per job, not per build.
* `maximum_bytes_billed` refusing at 1000 bytes shows the setting is enforced by BigQuery; it was
  not shown refusing at the configured 1 GB, because no job of the build comes near it.
