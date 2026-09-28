# Row-by-row join of the two value-parity legs (card t_48e969eb)

Generated 2026-09-28T07:25:27Z by `DBT_ENV=rows python3 scripts/row_join.py` (`make row-join DBT_ENV=rows`). DuckDB leg: `dev.duckdb`; BigQuery leg: `coreychimpbot.experiments_rows`; the fresh parity run of the same pair: `analyses/value_parity/fresh/results.md` (2026-09-28T08:15:06+0200).

## Verdict

**No row holds genuinely different money: 0 unexplained cents.**

All 55 money columns of 21 models (6605909 column-rows) joined on each model's key across L2, L9 and BigQuery: identical 1564764, **A** (same cents, different declared scale) 4767319, **B** (cents differ; the declared-scale emulation L9 reproduces BigQuery exactly) 273826, **C** (L9 does not reproduce BigQuery) 0.

L9 equals BigQuery exactly on 6605902 of 6605909 column-rows; the 7 others fall in identical 7 - the emulation is off there, not the money (see Where L9 is not BigQuery).

NULLs: 20037 column-rows are NULL on both legs (counted as identical); 0 are NULL on one leg only.

Every gate passed: source, rows, transfer. Every join matched every key (0 unmatched, 0 NULL, 0 duplicate keys on all three legs); both bucket invariants hold on every column.

The of-record pair (2026-09-27) cannot be joined row by row any more: the public source grew in between (see below).

## Why this is a fresh pair: the source moved after the of-record run

The of-record pair (`results.md`, BigQuery leg `coreychimpbot.experiments_dev`) can no longer be joined row by row. `bigquery-public-data.thelook_ecommerce` grew between the of-record load (2026-09-27T19:31:51Z, `logs/loader.log`) and this pair's load (2026-09-28T05:52:29Z, `logs/row_join_loader.log`); the of-record BigQuery tables are frozen at the old rows, its views and any DuckDB load read the new ones:

| table | rows of record | rows now | growth | bytes of record | bytes now |
|---|---|---|---|---|---|
| distribution_centers | 10 | 10 | 0 | 809 | 809 |
| products | 29120 | 29120 | 0 | 4285975 | 4285975 |
| users | 100000 | 100000 | 0 | 19818028 | 19816148 |
| inventory_items | 489625 | 492226 | 2601 | 81215181 | 81632957 |
| orders | 124952 | 125545 | 593 | 6748723 | 6780025 |
| order_items | 181313 | 182483 | 1170 | 13601246 | 13689221 |
| events | 2425698 | 2436872 | 11174 | 385279179 | 387026591 |

Recomputing the of-record values today (`logs/rows/of_record_gate.log`): on `coreychimpbot.experiments_dev` 57 of 99 recorded BigQuery values reproduce (all misses are views, which read the live source); on today's `dev.duckdb` 9 of 99 recorded DuckDB values do. Row counts that moved:

| model | recorded (both legs) | of-record BigQuery now | dev.duckdb now |
|---|---|---|---|
| fct_inventory_items | 489625 | 489625 | 492226 |
| fct_order_items | 181313 | 181313 | 182483 |
| fct_orders | 124952 | 124952 | 125545 |
| int_cohorts__user_months | 120667 | 121219 | 121219 |
| int_inventory__by_product_center | 29059 | 29054 | 29054 |
| int_inventory_items__enriched | 489625 | 492226 | 492226 |
| int_order_items__enriched | 181313 | 182483 | 182483 |
| int_orders__daily | 2761 | 2773 | 2773 |
| int_orders__item_rollup | 124952 | 125545 | 125545 |
| mart_cohort_retention | 3824 | 3824 | 3871 |
| mart_daily_revenue | 2761 | 2761 | 2773 |
| stg_thelook__inventory_items | 489625 | 492226 | 492226 |
| stg_thelook__order_items | 181313 | 182483 | 182483 |

## Gates

* **source** (pass): the seven `thelook_ecommerce` tables in `dev.duckdb` have today's BigQuery row count, and the money source columns (and `id`) hash identically on both sides (`parity.metrics_sql`, float rule):

| table | bigquery_rows | duckdb_rows | rows_equal | money_columns | metrics_equal |
|---|---|---|---|---|---|
| distribution_centers | 10 | 10 | True | - | - |
| products | 29120 | 29120 | True | id, cost, retail_price | True |
| users | 100000 | 100000 | True | - | - |
| inventory_items | 492226 | 492226 | True | id, cost, product_retail_price | True |
| orders | 125545 | 125545 | True | - | - |
| order_items | 182483 | 182483 | True | id, sale_price | True |
| events | 2436872 | 2436872 | True | - | - |

* **rows** (pass): per model, L2 = BigQuery (REST) = the fresh run's recorded count, 21 models.
* **transfer** (pass): `bq_leg.<model>`, measured in DuckDB with `metrics_sql`, equals the REST measurement of the same relation on every pulled column (255 metrics over 21 models); the REST measurement reproduces 94 of 94 values the fresh run recorded (`int_order_items__enriched` has no recorded values: the fresh run left it not_measured, see challenges).
* L2 is the fresh run's DuckDB leg: 94 of 94 recorded DuckDB values reproduce on today's `dev.duckdb`.

## L9: the DuckDB build with money_type() = decimal(38,9)

A copy of the tracked tree under `target/row_join/project/` built into schema `money9` of a copy of `dev.duckdb` (reused; built earlier today, `Summary: 196 total | 195 success | 1 warn`, `logs/rows/l9_build.log`). Validity against today's `dev.duckdb`: the seven source tables hash identically in dev.duckdb and in the copy (every column, parity.metrics_sql), the scratch models/ and macros/ equal the tree except the one line, money9 holds 29 relations. Every one of the 54 money_type() columns is `DECIMAL(38,9)` in `money9`. The copy differs from the repository only by:

```diff
diff --git a/macros/polyglot/types.sql b/target/row_join/project/macros/polyglot/types.sql
index 773bfd1..81dd55b 100644
--- a/macros/polyglot/types.sql
+++ b/target/row_join/project/macros/polyglot/types.sql
@@ -83,7 +83,7 @@
 {%- endmacro %}
 
 {% macro default__money_type() -%}
-    decimal(18,2)
+    decimal(38,9)
 {%- endmacro %}
 
 {% macro bigquery__money_type() -%}
```

## Per model

| model | key | BQ read | rows L2 / L9 / BQ | unmatched | null / dup keys | money cols | identical | A | B | C |
|---|---|---|---|---:|---|---:|---:|---:|---:|---:|
| dim_distribution_centers | `distribution_center_id` | bigquery_scan | 10 / 10 / 10 | 0 | 0 / 0 | 1 | 0 | 0 | 10 | 0 |
| dim_products | `product_id` | bigquery_scan | 29120 / 29120 / 29120 | 0 | 0 / 0 | 4 | 27161 | 68211 | 21108 | 0 |
| dim_users | `user_id` | bigquery_scan | 100000 / 100000 / 100000 | 0 | 0 / 0 | 2 | 61947 | 122518 | 15535 | 0 |
| fct_inventory_items | `inventory_item_id` | bigquery_scan | 492226 / 492226 / 492226 | 0 | 0 / 0 | 2 | 229012 | 755405 | 35 | 0 |
| fct_order_items | `inventory_item_id` (+`order_item_id` agree) | bigquery_scan | 182483 / 182483 / 182483 | 0 | 0 / 0 | 4 | 169844 | 559542 | 546 | 0 |
| fct_orders | `order_id` | bigquery_scan | 125545 / 125545 / 125545 | 0 | 0 / 0 | 3 | 47350 | 307295 | 21990 | 0 |
| int_cohorts__user_months | `user_month_key` | bigquery_query | 121219 / 121219 / 121219 | 0 | 0 / 0 | 1 | 44341 | 76878 | 0 | 0 |
| int_inventory__by_product_center | `product_center_key` | bigquery_query | 29054 / 29054 / 29054 | 0 | 0 / 0 | 2 | 13499 | 22046 | 22563 | 0 |
| int_inventory_items__enriched | `inventory_item_id` | bigquery_query | 492226 / 492226 / 492226 | 0 | 0 / 0 | 2 | 229012 | 755405 | 35 | 0 |
| int_order_items__enriched | `inventory_item_id` (+`order_item_id` agree) | bigquery_query | 182483 / 182483 / 182483 | 0 | 0 / 0 | 3 | 85430 | 461473 | 546 | 0 |
| int_orders__daily | `order_date` | bigquery_query | 2773 / 2773 / 2773 | 0 | 0 / 0 | 3 | 41 | 4029 | 4249 | 0 |
| int_orders__item_rollup | `order_id` | bigquery_query | 125545 / 125545 / 125545 | 0 | 0 / 0 | 3 | 47350 | 307295 | 21990 | 0 |
| int_products__sales | `product_id` | bigquery_query | 29120 / 29120 / 29120 | 0 | 0 / 0 | 3 | 13782 | 31364 | 42214 | 0 |
| int_users__lifetime_orders | `user_id` | bigquery_query | 100000 / 100000 / 100000 | 0 | 0 / 0 | 3 | 82012 | 187042 | 30946 | 0 |
| mart_cohort_retention | `cohort_activity_key` | bigquery_scan | 3871 / 3871 / 3871 | 0 | 0 / 0 | 1 | 251 | 3620 | 0 | 0 |
| mart_customer_summary | `user_id` | bigquery_scan | 100000 / 100000 / 100000 | 0 | 0 / 0 | 3 | 156535 | 122518 | 20947 | 0 |
| mart_daily_revenue | `revenue_date` | bigquery_scan | 2773 / 2773 / 2773 | 0 | 0 / 0 | 4 | 2772 | 4029 | 4291 | 0 |
| mart_product_performance | `product_id` | bigquery_scan | 29120 / 29120 / 29120 | 0 | 0 / 0 | 6 | 27469 | 80466 | 66785 | 0 |
| stg_thelook__inventory_items | `inventory_item_id` | bigquery_query | 492226 / 492226 / 492226 | 0 | 0 / 0 | 2 | 229012 | 755405 | 35 | 0 |
| stg_thelook__order_items | `order_item_id` | bigquery_query | 182483 / 182483 / 182483 | 0 | 0 / 0 | 1 | 84414 | 98069 | 0 | 0 |
| stg_thelook__products | `product_id` | bigquery_query | 29120 / 29120 / 29120 | 0 | 0 / 0 | 2 | 13530 | 44709 | 1 | 0 |
| **total** | | | | | | **55** | **1564764** | **4767319** | **273826** | **0** |

## Per column

Summary (rows compared = rows present on all three legs):

| column | rows | cents differ | delta range | raw differs | identical | A | B | C | L9 = BQ | NULL both / one side | C verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `dim_distribution_centers.open_inventory_value` | 10 | 10 | -8.99 .. +0.19 | 10 | 0 | 0 | 10 | 0 | 10 | 0 / 0 | no C rows |
| `dim_products.gross_margin` | 29120 | 21107 | -0.08 .. +0.08 | 28969 | 151 | 7862 | 21107 | 0 | 29120 | 0 / 0 | no C rows |
| `dim_products.gross_revenue` | 29120 | 0 | 0 | 15640 | 13480 | 15640 | 0 | 0 | 29120 | 0 / 0 | no C rows |
| `dim_products.retail_price` | 29120 | 0 | 0 | 15675 | 13445 | 15675 | 0 | 0 | 29120 | 0 / 0 | no C rows |
| `dim_products.unit_cost` | 29120 | 1 | +0.00 .. +0.01 | 29035 | 85 | 29034 | 1 | 0 | 29120 | 0 / 0 | no C rows |
| `dim_users.lifetime_gross_margin` | 100000 | 15535 | -0.03 .. +0.03 | 79935 | 20065 | 64400 | 15535 | 0 | 100000 | 0 / 0 | no C rows |
| `dim_users.lifetime_gross_revenue` | 100000 | 0 | 0 | 58118 | 41882 | 58118 | 0 | 0 | 100000 | 0 / 0 | no C rows |
| `fct_inventory_items.product_retail_price` | 492226 | 0 | 0 | 264590 | 227636 | 264590 | 0 | 0 | 492226 | 0 / 0 | no C rows |
| `fct_inventory_items.unit_cost` | 492226 | 35 | +0.00 .. +0.01 | 490850 | 1376 | 490815 | 35 | 0 | 492226 | 0 / 0 | no C rows |
| `fct_order_items.gross_margin` | 182483 | 534 | -0.01 .. +0.01 | 181975 | 508 | 181441 | 534 | 0 | 182483 | 0 / 0 | no C rows |
| `fct_order_items.product_cost` | 182483 | 12 | +0.00 .. +0.01 | 181975 | 508 | 181963 | 12 | 0 | 182483 | 0 / 0 | no C rows |
| `fct_order_items.product_retail_price` | 182483 | 0 | 0 | 98069 | 84414 | 98069 | 0 | 0 | 182483 | 0 / 0 | no C rows |
| `fct_order_items.sale_price` | 182483 | 0 | 0 | 98069 | 84414 | 98069 | 0 | 0 | 182483 | 0 / 0 | no C rows |
| `fct_orders.gross_margin` | 125545 | 11127 | -0.02 .. +0.02 | 125302 | 243 | 114175 | 11127 | 0 | 125545 | 0 / 0 | no C rows |
| `fct_orders.gross_revenue` | 125545 | 0 | 0 | 78681 | 46864 | 78681 | 0 | 0 | 125545 | 0 / 0 | no C rows |
| `fct_orders.total_cost` | 125545 | 10863 | -0.02 .. +0.02 | 125302 | 243 | 114439 | 10863 | 0 | 125545 | 0 / 0 | no C rows |
| `int_cohorts__user_months.revenue` | 121219 | 0 | 0 | 76878 | 44341 | 76878 | 0 | 0 | 121219 | 0 / 0 | no C rows |
| `int_inventory__by_product_center.open_inventory_value` | 29054 | 22563 | -0.14 .. +0.16 | 28969 | 85 | 6406 | 22563 | 0 | 29054 | 0 / 0 | no C rows |
| `int_inventory__by_product_center.open_retail_value` | 29054 | 0 | 0 | 15640 | 13414 | 15640 | 0 | 0 | 29054 | 0 / 0 | no C rows |
| `int_inventory_items__enriched.product_retail_price` | 492226 | 0 | 0 | 264590 | 227636 | 264590 | 0 | 0 | 492226 | 0 / 0 | no C rows |
| `int_inventory_items__enriched.unit_cost` | 492226 | 35 | +0.00 .. +0.01 | 490850 | 1376 | 490815 | 35 | 0 | 492226 | 0 / 0 | no C rows |
| `int_order_items__enriched.gross_margin` | 182483 | 534 | -0.01 .. +0.01 | 181975 | 508 | 181441 | 534 | 0 | 182483 | 0 / 0 | no C rows |
| `int_order_items__enriched.product_cost` | 182483 | 12 | +0.00 .. +0.01 | 181975 | 508 | 181963 | 12 | 0 | 182483 | 0 / 0 | no C rows |
| `int_order_items__enriched.sale_price` | 182483 | 0 | 0 | 98069 | 84414 | 98069 | 0 | 0 | 182483 | 0 / 0 | no C rows |
| `int_orders__daily.gross_margin` | 2773 | 2125 | -0.12 .. +0.43 | 2773 | 0 | 648 | 2125 | 0 | 2773 | 0 / 0 | no C rows |
| `int_orders__daily.gross_revenue` | 2773 | 0 | 0 | 2732 | 41 | 2732 | 0 | 0 | 2773 | 0 / 0 | no C rows |
| `int_orders__daily.total_cost` | 2773 | 2124 | -0.43 .. +0.12 | 2773 | 0 | 649 | 2124 | 0 | 2773 | 0 / 0 | no C rows |
| `int_orders__item_rollup.gross_margin` | 125545 | 11127 | -0.02 .. +0.02 | 125302 | 243 | 114175 | 11127 | 0 | 125545 | 0 / 0 | no C rows |
| `int_orders__item_rollup.gross_revenue` | 125545 | 0 | 0 | 78681 | 46864 | 78681 | 0 | 0 | 125545 | 0 / 0 | no C rows |
| `int_orders__item_rollup.total_cost` | 125545 | 10863 | -0.02 .. +0.02 | 125302 | 243 | 114439 | 10863 | 0 | 125545 | 0 / 0 | no C rows |
| `int_products__sales.gross_margin` | 29120 | 21107 | -0.08 .. +0.08 | 28969 | 151 | 7862 | 21107 | 0 | 29120 | 0 / 0 | no C rows |
| `int_products__sales.gross_revenue` | 29120 | 0 | 0 | 15640 | 13480 | 15640 | 0 | 0 | 29120 | 0 / 0 | no C rows |
| `int_products__sales.total_cost` | 29120 | 21107 | -0.08 .. +0.08 | 28969 | 151 | 7862 | 21107 | 0 | 29120 | 0 / 0 | no C rows |
| `int_users__lifetime_orders.lifetime_gross_margin` | 100000 | 15535 | -0.03 .. +0.03 | 79935 | 20065 | 64400 | 15535 | 0 | 100000 | 0 / 0 | no C rows |
| `int_users__lifetime_orders.lifetime_gross_revenue` | 100000 | 0 | 0 | 58118 | 41882 | 58118 | 0 | 0 | 100000 | 0 / 0 | no C rows |
| `int_users__lifetime_orders.lifetime_total_cost` | 100000 | 15411 | -0.03 .. +0.03 | 79935 | 20065 | 64524 | 15411 | 0 | 100000 | 0 / 0 | no C rows |
| `mart_cohort_retention.revenue` | 3871 | 0 | 0 | 3620 | 251 | 3620 | 0 | 0 | 3871 | 0 / 0 | no C rows |
| `mart_customer_summary.average_order_value` | 100000 | 5412 | -0.01 .. +0.01 | 5412 | 94588 | 0 | 5412 | 0 | 99993 | 19971 / 0 | no C rows |
| `mart_customer_summary.lifetime_gross_margin` | 100000 | 15535 | -0.03 .. +0.03 | 79935 | 20065 | 64400 | 15535 | 0 | 100000 | 0 / 0 | no C rows |
| `mart_customer_summary.lifetime_gross_revenue` | 100000 | 0 | 0 | 58118 | 41882 | 58118 | 0 | 0 | 100000 | 0 / 0 | no C rows |
| `mart_daily_revenue.average_order_value` | 2773 | 42 | -0.01 .. +0.01 | 42 | 2731 | 0 | 42 | 0 | 2773 | 0 / 0 | no C rows |
| `mart_daily_revenue.gross_margin` | 2773 | 2125 | -0.12 .. +0.43 | 2773 | 0 | 648 | 2125 | 0 | 2773 | 0 / 0 | no C rows |
| `mart_daily_revenue.gross_revenue` | 2773 | 0 | 0 | 2732 | 41 | 2732 | 0 | 0 | 2773 | 0 / 0 | no C rows |
| `mart_daily_revenue.total_cost` | 2773 | 2124 | -0.43 .. +0.12 | 2773 | 0 | 649 | 2124 | 0 | 2773 | 0 / 0 | no C rows |
| `mart_product_performance.gross_margin` | 29120 | 21107 | -0.08 .. +0.08 | 28969 | 151 | 7862 | 21107 | 0 | 29120 | 0 / 0 | no C rows |
| `mart_product_performance.gross_margin_rate` | 29120 | 24570 | -3159.00 .. +85000.00 | 28963 | 157 | 4393 | 24570 | 0 | 29120 | 66 / 0 | no C rows |
| `mart_product_performance.gross_revenue` | 29120 | 0 | 0 | 15640 | 13480 | 15640 | 0 | 0 | 29120 | 0 / 0 | no C rows |
| `mart_product_performance.retail_price` | 29120 | 0 | 0 | 15675 | 13445 | 15675 | 0 | 0 | 29120 | 0 / 0 | no C rows |
| `mart_product_performance.total_cost` | 29120 | 21107 | -0.08 .. +0.08 | 28969 | 151 | 7862 | 21107 | 0 | 29120 | 0 / 0 | no C rows |
| `mart_product_performance.unit_cost` | 29120 | 1 | +0.00 .. +0.01 | 29035 | 85 | 29034 | 1 | 0 | 29120 | 0 / 0 | no C rows |
| `stg_thelook__inventory_items.cost` | 492226 | 35 | +0.00 .. +0.01 | 490850 | 1376 | 490815 | 35 | 0 | 492226 | 0 / 0 | no C rows |
| `stg_thelook__inventory_items.product_retail_price` | 492226 | 0 | 0 | 264590 | 227636 | 264590 | 0 | 0 | 492226 | 0 / 0 | no C rows |
| `stg_thelook__order_items.sale_price` | 182483 | 0 | 0 | 98069 | 84414 | 98069 | 0 | 0 | 182483 | 0 / 0 | no C rows |
| `stg_thelook__products.cost` | 29120 | 1 | +0.00 .. +0.01 | 29035 | 85 | 29034 | 1 | 0 | 29120 | 0 / 0 | no C rows |
| `stg_thelook__products.retail_price` | 29120 | 0 | 0 | 15675 | 13445 | 15675 | 0 | 0 | 29120 | 0 / 0 | no C rows |

`delta range` is in dollars (1e-6 units for `gross_margin_rate`); a NULL on both legs is `identical` and its delta is NULL.

### `dim_distribution_centers.open_inventory_value`

money_type(); delta in dollars, at cents. Rows 10; cents differ 10; raw differs 10. identical 0, A 0, B 10, C 0; L9 = BQ exactly on 10 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/marts/dim_distribution_centers.sql:31: cast(coalesce(stock.open_inventory_value, 0) as {{ money_type() }}) as open_inventory_value`. C verdict: **no C rows**.

delta → rows: `-8.99` → 1, `-5.56` → 1, `-5.35` → 1, `-4.40` → 1, `-4.22` → 1, `-2.93` → 1, `-2.78` → 1, `-1.08` → 1, `-0.68` → 1, `0.19` → 1

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 1 | 1141040.83 | 1141035.270439304 | 1141035.270439304 | B |
| 2 | 1086750.74 | 1086750.930831553 | 1086750.930831553 | B |
| 3 | 1248313.90 | 1248304.907195048 | 1248304.907195048 | B |
| 4 | 786827.77 | 786822.423552274 | 786822.423552274 | B |
| 5 | 647543.23 | 647538.826563500 | 647538.826563500 | B |

### `dim_products.gross_margin`

money_type(); delta in dollars, at cents. Rows 29120; cents differ 21107; raw differs 28969. identical 151, A 7862, B 21107, C 0; L9 = BQ exactly on 29120 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/marts/dim_products.sql:53: sales.gross_margin,`. C verdict: **no C rows**.

delta → rows: `-0.08` → 3, `-0.07` → 15, `-0.06` → 60, `-0.05` → 248, `-0.04` → 833, `-0.03` → 1813, `-0.02` → 3171, `-0.01` → 4056, `0.00` → 8013, `0.01` → 4034, `0.02` → 3455, `0.03` → 2050, `0.04` → 971, `0.05` → 303, `0.06` → 78, `0.07` → 14, `0.08` → 3

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 1 | 153.65 | 153.664000588 | 153.664000588 | B |
| 2 | 65.74 | 65.747000162 | 65.747000162 | B |
| 3 | 171.00 | 170.970000840 | 170.970000840 | B |
| 4 | 305.22 | 305.208000540 | 305.208000540 | B |
| 5 | 249.84 | 249.852000774 | 249.852000774 | B |

### `dim_products.gross_revenue`

money_type(); delta in dollars, at cents. Rows 29120; cents differ 0; raw differs 15640. identical 13480, A 15640, B 0, C 0; L9 = BQ exactly on 29120 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/marts/dim_products.sql:52: sales.gross_revenue,`. C verdict: **no C rows**.

delta → rows: `0.00` → 29120

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 13 | 383.50 | 383.499984740 | 383.499984740 | A |
| 16 | 164.75 | 164.750003815 | 164.750003815 | A |
| 20 | 317.00 | 317.000007630 | 317.000007630 | A |
| 28 | 301.98 | 301.980010986 | 301.980010986 | A |
| 31 | 289.75 | 289.750003815 | 289.750003815 | A |

### `dim_products.retail_price`

money_type(); delta in dollars, at cents. Rows 29120; cents differ 0; raw differs 15675. identical 13445, A 15675, B 0, C 0; L9 = BQ exactly on 29120 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: direct cast, `models/marts/dim_products.sql:50: products.retail_price,`; source `thelook_ecommerce.products.retail_price`, checked on every row: {'n': 29120, 'l2_not_cast': 0, 'l9_not_cast': 0, 'bq_not_cast9': 0}. C verdict: **no C rows**.

delta → rows: `0.00` → 29120

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 13 | 76.70 | 76.699996948 | 76.699996948 | A |
| 16 | 32.95 | 32.950000763 | 32.950000763 | A |
| 20 | 63.40 | 63.400001526 | 63.400001526 | A |
| 28 | 150.99 | 150.990005493 | 150.990005493 | A |
| 31 | 57.95 | 57.950000763 | 57.950000763 | A |

### `dim_products.unit_cost`

money_type(); delta in dollars, at cents. Rows 29120; cents differ 1; raw differs 29035. identical 85, A 29034, B 1, C 0; L9 = BQ exactly on 29120 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: direct cast, `models/marts/dim_products.sql:49: products.cost                       as unit_cost,`; source `thelook_ecommerce.products.cost`, checked on every row: {'n': 29120, 'l2_not_cast': 0, 'l9_not_cast': 0, 'bq_not_cast9': 0}. C verdict: **no C rows**.

delta → rows: `0.00` → 29119, `0.01` → 1

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 9500 | 6.64 | 6.645000000 | 6.645000000 | B |

### `dim_users.lifetime_gross_margin`

money_type(); delta in dollars, at cents. Rows 100000; cents differ 15535; raw differs 79935. identical 20065, A 64400, B 15535, C 0; L9 = BQ exactly on 100000 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/marts/dim_users.sql:63: lifetime.lifetime_gross_margin,`. C verdict: **no C rows**.

delta → rows: `-0.03` → 1, `-0.02` → 141, `-0.01` → 6872, `0.00` → 84465, `0.01` → 8259, `0.02` → 258, `0.03` → 4

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 2 | 143.55 | 143.538069680 | 143.538069680 | B |
| 4 | 134.97 | 134.957097914 | 134.957097914 | B |
| 5 | 133.43 | 133.419457174 | 133.419457174 | B |
| 9 | 122.34 | 122.350826847 | 122.350826847 | B |
| 14 | 142.60 | 142.589841029 | 142.589841029 | B |

### `dim_users.lifetime_gross_revenue`

money_type(); delta in dollars, at cents. Rows 100000; cents differ 0; raw differs 58118. identical 41882, A 58118, B 0, C 0; L9 = BQ exactly on 100000 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/marts/dim_users.sql:62: lifetime.lifetime_gross_revenue,`. C verdict: **no C rows**.

delta → rows: `0.00` → 100000

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 1 | 235.97 | 235.970001220 | 235.970001220 | A |
| 2 | 271.83 | 271.829998970 | 271.829998970 | A |
| 3 | 9.95 | 9.949999809 | 9.949999809 | A |
| 4 | 288.00 | 287.999996186 | 287.999996186 | A |
| 5 | 239.94 | 239.939994812 | 239.939994812 | A |

### `fct_inventory_items.product_retail_price`

money_type(); delta in dollars, at cents. Rows 492226; cents differ 0; raw differs 264590. identical 227636, A 264590, B 0, C 0; L9 = BQ exactly on 492226 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: direct cast, `models/marts/fct_inventory_items.sql:7: product_retail_price,`; source `thelook_ecommerce.inventory_items.product_retail_price`, checked on every row: {'n': 492226, 'l2_not_cast': 0, 'l9_not_cast': 0, 'bq_not_cast9': 0}. C verdict: **no C rows**.

delta → rows: `0.00` → 492226

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 1 | 44.98 | 44.979999542 | 44.979999542 | A |
| 2 | 44.98 | 44.979999542 | 44.979999542 | A |
| 3 | 44.98 | 44.979999542 | 44.979999542 | A |
| 4 | 44.98 | 44.979999542 | 44.979999542 | A |
| 5 | 34.99 | 34.990001678 | 34.990001678 | A |

### `fct_inventory_items.unit_cost`

money_type(); delta in dollars, at cents. Rows 492226; cents differ 35; raw differs 490850. identical 1376, A 490815, B 35, C 0; L9 = BQ exactly on 492226 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: direct cast, `models/marts/fct_inventory_items.sql:6: unit_cost,`; source `thelook_ecommerce.inventory_items.cost`, checked on every row: {'n': 492226, 'l2_not_cast': 0, 'l9_not_cast': 0, 'bq_not_cast9': 0}. C verdict: **no C rows**.

delta → rows: `0.00` → 492191, `0.01` → 35

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 3630 | 6.64 | 6.645000000 | 6.645000000 | B |
| 3631 | 6.64 | 6.645000000 | 6.645000000 | B |
| 7142 | 6.64 | 6.645000000 | 6.645000000 | B |
| 7143 | 6.64 | 6.645000000 | 6.645000000 | B |
| 7144 | 6.64 | 6.645000000 | 6.645000000 | B |

### `fct_order_items.gross_margin`

money_type(); delta in dollars, at cents. Rows 182483; cents differ 534; raw differs 181975. identical 508, A 181441, B 534, C 0; L9 = BQ exactly on 182483 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/marts/fct_order_items.sql:53: order_items.gross_margin,`. C verdict: **no C rows**.

delta → rows: `-0.01` → 249, `0.00` → 181949, `0.01` → 285

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 305 | 6.90 | 6.894999981 | 6.894999981 | B |
| 798 | 15.90 | 15.894999812 | 15.894999812 | B |
| 2973 | 9.37 | 9.375000000 | 9.375000000 | B |
| 6007 | 6.90 | 6.894999981 | 6.894999981 | B |
| 6246 | 22.49 | 22.495000839 | 22.495000839 | B |

### `fct_order_items.product_cost`

money_type(); delta in dollars, at cents. Rows 182483; cents differ 12; raw differs 181975. identical 508, A 181963, B 12, C 0; L9 = BQ exactly on 182483 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: direct cast, `models/marts/fct_order_items.sql:52: order_items.product_cost,`; source `thelook_ecommerce.inventory_items.cost`, checked on every row: {'n': 182483, 'l2_not_cast': 0, 'l9_not_cast': 0, 'bq_not_cast9': 0}. C verdict: **no C rows**.

delta → rows: `0.00` → 182471, `0.01` → 12

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 3631 | 6.64 | 6.645000000 | 6.645000000 | B |
| 7144 | 6.64 | 6.645000000 | 6.645000000 | B |
| 39523 | 6.64 | 6.645000000 | 6.645000000 | B |
| 61665 | 6.64 | 6.645000000 | 6.645000000 | B |
| 101817 | 6.64 | 6.645000000 | 6.645000000 | B |

### `fct_order_items.product_retail_price`

money_type(); delta in dollars, at cents. Rows 182483; cents differ 0; raw differs 98069. identical 84414, A 98069, B 0, C 0; L9 = BQ exactly on 182483 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: direct cast, `models/marts/fct_order_items.sql:61: products.retail_price               as product_retail_price,`; source `thelook_ecommerce.products.retail_price`, checked on every row: {'n': 182483, 'l2_not_cast': 0, 'l9_not_cast': 0, 'bq_not_cast9': 0}. C verdict: **no C rows**.

delta → rows: `0.00` → 182483

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 4 | 44.98 | 44.979999542 | 44.979999542 | A |
| 7 | 34.99 | 34.990001678 | 34.990001678 | A |
| 17 | 49.94 | 49.939998627 | 49.939998627 | A |
| 19 | 39.95 | 39.950000763 | 39.950000763 | A |
| 21 | 21.99 | 21.989999771 | 21.989999771 | A |

### `fct_order_items.sale_price`

money_type(); delta in dollars, at cents. Rows 182483; cents differ 0; raw differs 98069. identical 84414, A 98069, B 0, C 0; L9 = BQ exactly on 182483 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: direct cast, `models/marts/fct_order_items.sql:51: order_items.sale_price,`; source `thelook_ecommerce.order_items.sale_price`, checked on every row: {'n': 182483, 'l2_not_cast': 0, 'l9_not_cast': 0, 'bq_not_cast9': 0}. C verdict: **no C rows**.

delta → rows: `0.00` → 182483

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 4 | 44.98 | 44.979999542 | 44.979999542 | A |
| 7 | 34.99 | 34.990001678 | 34.990001678 | A |
| 17 | 49.94 | 49.939998627 | 49.939998627 | A |
| 19 | 39.95 | 39.950000763 | 39.950000763 | A |
| 21 | 21.99 | 21.989999771 | 21.989999771 | A |

### `fct_orders.gross_margin`

money_type(); delta in dollars, at cents. Rows 125545; cents differ 11127; raw differs 125302. identical 243, A 114175, B 11127, C 0; L9 = BQ exactly on 125545 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/marts/fct_orders.sql:39: orders.gross_margin,`. C verdict: **no C rows**.

delta → rows: `-0.02` → 14, `-0.01` → 4995, `0.00` → 114418, `0.01` → 6084, `0.02` → 34

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 7 | 54.02 | 54.014728691 | 54.014728691 | B |
| 12 | 96.70 | 96.693958653 | 96.693958653 | B |
| 16 | 122.34 | 122.350826847 | 122.350826847 | B |
| 20 | 142.60 | 142.589841029 | 142.589841029 | B |
| 31 | 48.37 | 48.376861034 | 48.376861034 | B |

### `fct_orders.gross_revenue`

money_type(); delta in dollars, at cents. Rows 125545; cents differ 0; raw differs 78681. identical 46864, A 78681, B 0, C 0; L9 = BQ exactly on 125545 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/marts/fct_orders.sql:37: orders.gross_revenue,`. C verdict: **no C rows**.

delta → rows: `0.00` → 125545

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 1 | 235.97 | 235.970001220 | 235.970001220 | A |
| 2 | 49.94 | 49.939998627 | 49.939998627 | A |
| 3 | 39.95 | 39.950000763 | 39.950000763 | A |
| 4 | 21.99 | 21.989999771 | 21.989999771 | A |
| 5 | 159.95 | 159.949999809 | 159.949999809 | A |

### `fct_orders.total_cost`

money_type(); delta in dollars, at cents. Rows 125545; cents differ 10863; raw differs 125302. identical 243, A 114439, B 10863, C 0; L9 = BQ exactly on 125545 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/marts/fct_orders.sql:38: orders.total_cost,`. C verdict: **no C rows**.

delta → rows: `-0.02` → 34, `-0.01` → 5944, `0.00` → 114682, `0.01` → 4871, `0.02` → 14

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 7 | 45.96 | 45.965268944 | 45.965268944 | B |
| 12 | 68.29 | 68.296039211 | 68.296039211 | B |
| 16 | 93.51 | 93.499167812 | 93.499167812 | B |
| 20 | 158.33 | 158.340161183 | 158.340161183 | B |
| 31 | 45.83 | 45.823140682 | 45.823140682 | B |

### `int_cohorts__user_months.revenue`

money_type(); delta in dollars, at cents. Rows 121219; cents differ 0; raw differs 76878. identical 44341, A 76878, B 0, C 0; L9 = BQ exactly on 121219 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/intermediate/int_cohorts__user_months.sql:43: cast(user_months.revenue as {{ money_type() }})     as revenue`. C verdict: **no C rows**.

delta → rows: `0.00` → 121219

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 0000ae018ce1ba062c15053d4bcffdee | 78.13 | 78.129997253 | 78.129997253 | A |
| 0001429ba0bb4c4d7eb8283e3e420ba1 | 44.99 | 44.990001678 | 44.990001678 | A |
| 0002ff7fa54e373c78e9f26a63476b90 | 163.54 | 163.539997101 | 163.539997101 | A |
| 00045553e28a033a949b64814803826d | 34.82 | 34.819999695 | 34.819999695 | A |
| 00066f27790caaf76beea917479e4d5a | 13.79 | 13.789999962 | 13.789999962 | A |

### `int_inventory__by_product_center.open_inventory_value`

money_type(); delta in dollars, at cents. Rows 29054; cents differ 22563; raw differs 28969. identical 85, A 6406, B 22563, C 0; L9 = BQ exactly on 29054 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/intermediate/int_inventory__by_product_center.sql:25: cast(open_inventory_value as {{ money_type() }})                        as open_inventory_value,`. C verdict: **no C rows**.

delta → rows: `-0.14` → 2, `-0.13` → 10, `-0.12` → 13, `-0.11` → 35, `-0.10` → 73, `-0.09` → 130, `-0.08` → 267, `-0.07` → 520, `-0.06` → 870, `-0.05` → 1146, `-0.04` → 1709, `-0.03` → 2019, `-0.02` → 2424, `-0.01` → 2399, `0.00` → 6491, `0.01` → 2409, `0.02` → 2444, `0.03` → 1890, `0.04` → 1533, `0.05` → 1014, `0.06` → 756, `0.07` → 390, `0.08` → 280, `0.09` → 103, `0.10` → 78, `0.11` → 25, `0.12` → 13, `0.13` → 7, `0.14` → 3, `0.16` → 1

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 00031a75eb3acff3634f6425dfc550e1 | 335.83 | 335.877854972 | 335.877854972 | B |
| 00037bc6fcd9f8170b02996c205889c4 | 86.40 | 86.469120144 | 86.469120144 | B |
| 0004e7e0778aaa0e008b712ca018219b | 206.64 | 206.660156355 | 206.660156355 | B |
| 000d616851489120531f8d06f16c45ad | 1933.63 | 1933.667994623 | 1933.667994623 | B |
| 00120d14e6df9045b08b29f89bea1e37 | 38.57 | 38.554319202 | 38.554319202 | B |

### `int_inventory__by_product_center.open_retail_value`

money_type(); delta in dollars, at cents. Rows 29054; cents differ 0; raw differs 15640. identical 13414, A 15640, B 0, C 0; L9 = BQ exactly on 29054 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/intermediate/int_inventory__by_product_center.sql:26: cast(open_retail_value as {{ money_type() }})                           as open_retail_value`. C verdict: **no C rows**.

delta → rows: `0.00` → 29054

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 00031a75eb3acff3634f6425dfc550e1 | 652.19 | 652.190010076 | 652.190010076 | A |
| 00037bc6fcd9f8170b02996c205889c4 | 207.36 | 207.360000608 | 207.360000608 | A |
| 0004e7e0778aaa0e008b712ca018219b | 440.64 | 440.639991756 | 440.639991756 | A |
| 00120d14e6df9045b08b29f89bea1e37 | 90.93 | 90.929998397 | 90.929998397 | A |
| 001992bdda958eda60ffbd566f92f891 | 311.92 | 311.920013424 | 311.920013424 | A |

### `int_inventory_items__enriched.product_retail_price`

money_type(); delta in dollars, at cents. Rows 492226; cents differ 0; raw differs 264590. identical 227636, A 264590, B 0, C 0; L9 = BQ exactly on 492226 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: direct cast, `models/intermediate/int_inventory_items__enriched.sql:13: product_retail_price,`; source `thelook_ecommerce.inventory_items.product_retail_price`, checked on every row: {'n': 492226, 'l2_not_cast': 0, 'l9_not_cast': 0, 'bq_not_cast9': 0}. C verdict: **no C rows**.

delta → rows: `0.00` → 492226

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 1 | 44.98 | 44.979999542 | 44.979999542 | A |
| 2 | 44.98 | 44.979999542 | 44.979999542 | A |
| 3 | 44.98 | 44.979999542 | 44.979999542 | A |
| 4 | 44.98 | 44.979999542 | 44.979999542 | A |
| 5 | 34.99 | 34.990001678 | 34.990001678 | A |

### `int_inventory_items__enriched.unit_cost`

money_type(); delta in dollars, at cents. Rows 492226; cents differ 35; raw differs 490850. identical 1376, A 490815, B 35, C 0; L9 = BQ exactly on 492226 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: direct cast, `models/intermediate/int_inventory_items__enriched.sql:12: cost                                                        as unit_cost,`; source `thelook_ecommerce.inventory_items.cost`, checked on every row: {'n': 492226, 'l2_not_cast': 0, 'l9_not_cast': 0, 'bq_not_cast9': 0}. C verdict: **no C rows**.

delta → rows: `0.00` → 492191, `0.01` → 35

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 3630 | 6.64 | 6.645000000 | 6.645000000 | B |
| 3631 | 6.64 | 6.645000000 | 6.645000000 | B |
| 7142 | 6.64 | 6.645000000 | 6.645000000 | B |
| 7143 | 6.64 | 6.645000000 | 6.645000000 | B |
| 7144 | 6.64 | 6.645000000 | 6.645000000 | B |

### `int_order_items__enriched.gross_margin`

money_type(); delta in dollars, at cents. Rows 182483; cents differ 534; raw differs 181975. identical 508, A 181441, B 534, C 0; L9 = BQ exactly on 182483 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/intermediate/int_order_items__enriched.sql:60: cast(order_items.sale_price - inventory_items.cost as {{ money_type() }}) as gross_margin,`. C verdict: **no C rows**.

delta → rows: `-0.01` → 249, `0.00` → 181949, `0.01` → 285

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 305 | 6.90 | 6.894999981 | 6.894999981 | B |
| 798 | 15.90 | 15.894999812 | 15.894999812 | B |
| 2973 | 9.37 | 9.375000000 | 9.375000000 | B |
| 6007 | 6.90 | 6.894999981 | 6.894999981 | B |
| 6246 | 22.49 | 22.495000839 | 22.495000839 | B |

### `int_order_items__enriched.product_cost`

money_type(); delta in dollars, at cents. Rows 182483; cents differ 12; raw differs 181975. identical 508, A 181963, B 12, C 0; L9 = BQ exactly on 182483 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: direct cast, `models/intermediate/int_order_items__enriched.sql:59: inventory_items.cost                                                    as product_cost,`; source `thelook_ecommerce.inventory_items.cost`, checked on every row: {'n': 182483, 'l2_not_cast': 0, 'l9_not_cast': 0, 'bq_not_cast9': 0}. C verdict: **no C rows**.

delta → rows: `0.00` → 182471, `0.01` → 12

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 3631 | 6.64 | 6.645000000 | 6.645000000 | B |
| 7144 | 6.64 | 6.645000000 | 6.645000000 | B |
| 39523 | 6.64 | 6.645000000 | 6.645000000 | B |
| 61665 | 6.64 | 6.645000000 | 6.645000000 | B |
| 101817 | 6.64 | 6.645000000 | 6.645000000 | B |

### `int_order_items__enriched.sale_price`

money_type(); delta in dollars, at cents. Rows 182483; cents differ 0; raw differs 98069. identical 84414, A 98069, B 0, C 0; L9 = BQ exactly on 182483 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: direct cast, `models/intermediate/int_order_items__enriched.sql:58: order_items.sale_price,`; source `thelook_ecommerce.order_items.sale_price`, checked on every row: {'n': 182483, 'l2_not_cast': 0, 'l9_not_cast': 0, 'bq_not_cast9': 0}. C verdict: **no C rows**.

delta → rows: `0.00` → 182483

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 4 | 44.98 | 44.979999542 | 44.979999542 | A |
| 7 | 34.99 | 34.990001678 | 34.990001678 | A |
| 17 | 49.94 | 49.939998627 | 49.939998627 | A |
| 19 | 39.95 | 39.950000763 | 39.950000763 | A |
| 21 | 21.99 | 21.989999771 | 21.989999771 | A |

### `int_orders__daily.gross_margin`

money_type(); delta in dollars, at cents. Rows 2773; cents differ 2125; raw differs 2773. identical 0, A 648, B 2125, C 0; L9 = BQ exactly on 2773 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/intermediate/int_orders__daily.sql:10: cast(sum(gross_margin) as {{ money_type() }})           as gross_margin,`. C verdict: **no C rows**.

delta → rows: `-0.12` → 1, `-0.09` → 1, `-0.08` → 3, `-0.07` → 6, `-0.06` → 13, `-0.05` → 10, `-0.04` → 42, `-0.03` → 94, `-0.02` → 200, `-0.01` → 432, `0.00` → 648, `0.01` → 492, `0.02` → 309, `0.03` → 199, `0.04` → 112, `0.05` → 78, `0.06` → 42, `0.07` → 33, `0.08` → 14, `0.09` → 23, `0.10` → 7, `0.11` → 7, `0.12` → 2, `0.14` → 2, `0.16` → 1, `0.26` → 1, `0.43` → 1

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 2019-01-10 | 65.99 | 65.983120470 | 65.983120470 | B |
| 2019-01-30 | 58.57 | 58.562250446 | 58.562250446 | B |
| 2019-02-15 | 151.27 | 151.262809748 | 151.262809748 | B |
| 2019-02-24 | 71.30 | 71.307440417 | 71.307440417 | B |
| 2019-03-08 | 109.57 | 109.577882325 | 109.577882325 | B |

### `int_orders__daily.gross_revenue`

money_type(); delta in dollars, at cents. Rows 2773; cents differ 0; raw differs 2732. identical 41, A 2732, B 0, C 0; L9 = BQ exactly on 2773 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/intermediate/int_orders__daily.sql:8: cast(sum(gross_revenue) as {{ money_type() }})          as gross_revenue,`. C verdict: **no C rows**.

delta → rows: `0.00` → 2773

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 2019-01-10 | 114.78 | 114.780000687 | 114.780000687 | A |
| 2019-01-12 | 135.77 | 135.769998550 | 135.769998550 | A |
| 2019-01-17 | 33.98 | 33.979999542 | 33.979999542 | A |
| 2019-01-26 | 190.94 | 190.940006256 | 190.940006256 | A |
| 2019-01-30 | 116.45 | 116.450000763 | 116.450000763 | A |

### `int_orders__daily.total_cost`

money_type(); delta in dollars, at cents. Rows 2773; cents differ 2124; raw differs 2773. identical 0, A 649, B 2124, C 0; L9 = BQ exactly on 2773 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/intermediate/int_orders__daily.sql:9: cast(sum(total_cost) as {{ money_type() }})             as total_cost,`. C verdict: **no C rows**.

delta → rows: `-0.43` → 1, `-0.26` → 1, `-0.16` → 1, `-0.14` → 2, `-0.12` → 2, `-0.11` → 7, `-0.10` → 7, `-0.09` → 23, `-0.08` → 14, `-0.07` → 33, `-0.06` → 42, `-0.05` → 77, `-0.04` → 112, `-0.03` → 200, `-0.02` → 309, `-0.01` → 491, `0.00` → 649, `0.01` → 432, `0.02` → 200, `0.03` → 94, `0.04` → 43, `0.05` → 9, `0.06` → 13, `0.07` → 6, `0.08` → 3, `0.09` → 1, `0.12` → 1

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 2019-01-10 | 48.79 | 48.796880217 | 48.796880217 | B |
| 2019-01-30 | 57.88 | 57.887750317 | 57.887750317 | B |
| 2019-02-15 | 152.48 | 152.487190252 | 152.487190252 | B |
| 2019-02-24 | 60.22 | 60.212560041 | 60.212560041 | B |
| 2019-03-08 | 82.61 | 82.602121794 | 82.602121794 | B |

### `int_orders__item_rollup.gross_margin`

money_type(); delta in dollars, at cents. Rows 125545; cents differ 11127; raw differs 125302. identical 243, A 114175, B 11127, C 0; L9 = BQ exactly on 125545 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/intermediate/int_orders__item_rollup.sql:34: cast(coalesce(item_totals.gross_margin, 0) as {{ money_type() }})       as gross_margin,`. C verdict: **no C rows**.

delta → rows: `-0.02` → 14, `-0.01` → 4995, `0.00` → 114418, `0.01` → 6084, `0.02` → 34

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 7 | 54.02 | 54.014728691 | 54.014728691 | B |
| 12 | 96.70 | 96.693958653 | 96.693958653 | B |
| 16 | 122.34 | 122.350826847 | 122.350826847 | B |
| 20 | 142.60 | 142.589841029 | 142.589841029 | B |
| 31 | 48.37 | 48.376861034 | 48.376861034 | B |

### `int_orders__item_rollup.gross_revenue`

money_type(); delta in dollars, at cents. Rows 125545; cents differ 0; raw differs 78681. identical 46864, A 78681, B 0, C 0; L9 = BQ exactly on 125545 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/intermediate/int_orders__item_rollup.sql:32: cast(coalesce(item_totals.gross_revenue, 0) as {{ money_type() }})      as gross_revenue,`. C verdict: **no C rows**.

delta → rows: `0.00` → 125545

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 1 | 235.97 | 235.970001220 | 235.970001220 | A |
| 2 | 49.94 | 49.939998627 | 49.939998627 | A |
| 3 | 39.95 | 39.950000763 | 39.950000763 | A |
| 4 | 21.99 | 21.989999771 | 21.989999771 | A |
| 5 | 159.95 | 159.949999809 | 159.949999809 | A |

### `int_orders__item_rollup.total_cost`

money_type(); delta in dollars, at cents. Rows 125545; cents differ 10863; raw differs 125302. identical 243, A 114439, B 10863, C 0; L9 = BQ exactly on 125545 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/intermediate/int_orders__item_rollup.sql:33: cast(coalesce(item_totals.total_cost, 0) as {{ money_type() }})         as total_cost,`. C verdict: **no C rows**.

delta → rows: `-0.02` → 34, `-0.01` → 5944, `0.00` → 114682, `0.01` → 4871, `0.02` → 14

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 7 | 45.96 | 45.965268944 | 45.965268944 | B |
| 12 | 68.29 | 68.296039211 | 68.296039211 | B |
| 16 | 93.51 | 93.499167812 | 93.499167812 | B |
| 20 | 158.33 | 158.340161183 | 158.340161183 | B |
| 31 | 45.83 | 45.823140682 | 45.823140682 | B |

### `int_products__sales.gross_margin`

money_type(); delta in dollars, at cents. Rows 29120; cents differ 21107; raw differs 28969. identical 151, A 7862, B 21107, C 0; L9 = BQ exactly on 29120 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/intermediate/int_products__sales.sql:32: cast(coalesce(sales.gross_margin, 0) as {{ money_type() }})     as gross_margin,`. C verdict: **no C rows**.

delta → rows: `-0.08` → 3, `-0.07` → 15, `-0.06` → 60, `-0.05` → 248, `-0.04` → 833, `-0.03` → 1813, `-0.02` → 3171, `-0.01` → 4056, `0.00` → 8013, `0.01` → 4034, `0.02` → 3455, `0.03` → 2050, `0.04` → 971, `0.05` → 303, `0.06` → 78, `0.07` → 14, `0.08` → 3

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 1 | 153.65 | 153.664000588 | 153.664000588 | B |
| 2 | 65.74 | 65.747000162 | 65.747000162 | B |
| 3 | 171.00 | 170.970000840 | 170.970000840 | B |
| 4 | 305.22 | 305.208000540 | 305.208000540 | B |
| 5 | 249.84 | 249.852000774 | 249.852000774 | B |

### `int_products__sales.gross_revenue`

money_type(); delta in dollars, at cents. Rows 29120; cents differ 0; raw differs 15640. identical 13480, A 15640, B 0, C 0; L9 = BQ exactly on 29120 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/intermediate/int_products__sales.sql:30: cast(coalesce(sales.gross_revenue, 0) as {{ money_type() }})    as gross_revenue,`. C verdict: **no C rows**.

delta → rows: `0.00` → 29120

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 13 | 383.50 | 383.499984740 | 383.499984740 | A |
| 16 | 164.75 | 164.750003815 | 164.750003815 | A |
| 20 | 317.00 | 317.000007630 | 317.000007630 | A |
| 28 | 301.98 | 301.980010986 | 301.980010986 | A |
| 31 | 289.75 | 289.750003815 | 289.750003815 | A |

### `int_products__sales.total_cost`

money_type(); delta in dollars, at cents. Rows 29120; cents differ 21107; raw differs 28969. identical 151, A 7862, B 21107, C 0; L9 = BQ exactly on 29120 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/intermediate/int_products__sales.sql:31: cast(coalesce(sales.total_cost, 0) as {{ money_type() }})       as total_cost,`. C verdict: **no C rows**.

delta → rows: `-0.08` → 3, `-0.07` → 14, `-0.06` → 78, `-0.05` → 300, `-0.04` → 965, `-0.03` → 2052, `-0.02` → 3454, `-0.01` → 4043, `0.00` → 8013, `0.01` → 4059, `0.02` → 3173, `0.03` → 1812, `0.04` → 831, `0.05` → 245, `0.06` → 61, `0.07` → 14, `0.08` → 3

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 1 | 189.35 | 189.335999412 | 189.335999412 | B |
| 2 | 73.26 | 73.252999838 | 73.252999838 | B |
| 3 | 246.00 | 246.029999160 | 246.029999160 | B |
| 4 | 342.78 | 342.791999460 | 342.791999460 | B |
| 5 | 314.16 | 314.147999226 | 314.147999226 | B |

### `int_users__lifetime_orders.lifetime_gross_margin`

money_type(); delta in dollars, at cents. Rows 100000; cents differ 15535; raw differs 79935. identical 20065, A 64400, B 15535, C 0; L9 = BQ exactly on 100000 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/intermediate/int_users__lifetime_orders.sql:35: cast(coalesce(order_totals.lifetime_gross_margin, 0) as {{ money_type() }})         as lifetime_gross_margin,`. C verdict: **no C rows**.

delta → rows: `-0.03` → 1, `-0.02` → 141, `-0.01` → 6872, `0.00` → 84465, `0.01` → 8259, `0.02` → 258, `0.03` → 4

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 2 | 143.55 | 143.538069680 | 143.538069680 | B |
| 4 | 134.97 | 134.957097914 | 134.957097914 | B |
| 5 | 133.43 | 133.419457174 | 133.419457174 | B |
| 9 | 122.34 | 122.350826847 | 122.350826847 | B |
| 14 | 142.60 | 142.589841029 | 142.589841029 | B |

### `int_users__lifetime_orders.lifetime_gross_revenue`

money_type(); delta in dollars, at cents. Rows 100000; cents differ 0; raw differs 58118. identical 41882, A 58118, B 0, C 0; L9 = BQ exactly on 100000 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/intermediate/int_users__lifetime_orders.sql:33: cast(coalesce(order_totals.lifetime_gross_revenue, 0) as {{ money_type() }})        as lifetime_gross_revenue,`. C verdict: **no C rows**.

delta → rows: `0.00` → 100000

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 1 | 235.97 | 235.970001220 | 235.970001220 | A |
| 2 | 271.83 | 271.829998970 | 271.829998970 | A |
| 3 | 9.95 | 9.949999809 | 9.949999809 | A |
| 4 | 288.00 | 287.999996186 | 287.999996186 | A |
| 5 | 239.94 | 239.939994812 | 239.939994812 | A |

### `int_users__lifetime_orders.lifetime_total_cost`

money_type(); delta in dollars, at cents. Rows 100000; cents differ 15411; raw differs 79935. identical 20065, A 64524, B 15411, C 0; L9 = BQ exactly on 100000 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/intermediate/int_users__lifetime_orders.sql:34: cast(coalesce(order_totals.lifetime_total_cost, 0) as {{ money_type() }})           as lifetime_total_cost,`. C verdict: **no C rows**.

delta → rows: `-0.03` → 4, `-0.02` → 257, `-0.01` → 8193, `0.00` → 84589, `0.01` → 6815, `0.02` → 141, `0.03` → 1

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 2 | 128.28 | 128.291929290 | 128.291929290 | B |
| 4 | 153.03 | 153.042898272 | 153.042898272 | B |
| 5 | 106.51 | 106.520537638 | 106.520537638 | B |
| 9 | 93.51 | 93.499167812 | 93.499167812 | B |
| 14 | 158.33 | 158.340161183 | 158.340161183 | B |

### `mart_cohort_retention.revenue`

money_type(); delta in dollars, at cents. Rows 3871; cents differ 0; raw differs 3620. identical 251, A 3620, B 0, C 0; L9 = BQ exactly on 3871 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/marts/mart_cohort_retention.sql:44: cast(cohort_months.revenue as {{ money_type() }})               as revenue,`. C verdict: **no C rows**.

delta → rows: `0.00` → 3871

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 0000765532832799627eff063d60218d | 1614.19 | 1614.189999578 | 1614.189999578 | A |
| 0001133d6fe5852a60dcbcc7a431ad59 | 649.08 | 649.079999208 | 649.079999208 | A |
| 002c1ccb6b8e260da7d0cfd66a55c363 | 273.95 | 273.949996948 | 273.949996948 | A |
| 00342b67b07579dd0aba60d410a625bf | 772.01 | 772.009997367 | 772.009997367 | A |
| 005fc9335ece1e4bdc363c9f82f10f52 | 1116.98 | 1116.979994774 | 1116.979994774 | A |

### `mart_customer_summary.average_order_value`

money_type(); delta in dollars, at cents. Rows 100000; cents differ 5412; raw differs 5412. identical 94588, A 0, B 5412, C 0; L9 = BQ exactly on 99993 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/marts/mart_customer_summary.sql:39: cast(round(users.lifetime_gross_revenue / nullif(users.lifetime_orders, 0), 2) as {{ money_type() }})                                      as average_order_value,`. C verdict: **no C rows**.

delta → rows: `-0.01` → 4970, `0.00` → 74617, `0.01` → 442, `NULL` → 19971

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 29 | 91.00 | 90.990000000 | 90.990000000 | B |
| 79 | 212.47 | 212.460000000 | 212.460000000 | B |
| 104 | 112.23 | 112.220000000 | 112.220000000 | B |
| 113 | 42.73 | 42.720000000 | 42.720000000 | B |
| 120 | 107.78 | 107.770000000 | 107.770000000 | B |

### `mart_customer_summary.lifetime_gross_margin`

money_type(); delta in dollars, at cents. Rows 100000; cents differ 15535; raw differs 79935. identical 20065, A 64400, B 15535, C 0; L9 = BQ exactly on 100000 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/marts/mart_customer_summary.sql:38: users.lifetime_gross_margin,`. C verdict: **no C rows**.

delta → rows: `-0.03` → 1, `-0.02` → 141, `-0.01` → 6872, `0.00` → 84465, `0.01` → 8259, `0.02` → 258, `0.03` → 4

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 2 | 143.55 | 143.538069680 | 143.538069680 | B |
| 4 | 134.97 | 134.957097914 | 134.957097914 | B |
| 5 | 133.43 | 133.419457174 | 133.419457174 | B |
| 9 | 122.34 | 122.350826847 | 122.350826847 | B |
| 14 | 142.60 | 142.589841029 | 142.589841029 | B |

### `mart_customer_summary.lifetime_gross_revenue`

money_type(); delta in dollars, at cents. Rows 100000; cents differ 0; raw differs 58118. identical 41882, A 58118, B 0, C 0; L9 = BQ exactly on 100000 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/marts/mart_customer_summary.sql:37: users.lifetime_gross_revenue,`. C verdict: **no C rows**.

delta → rows: `0.00` → 100000

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 1 | 235.97 | 235.970001220 | 235.970001220 | A |
| 2 | 271.83 | 271.829998970 | 271.829998970 | A |
| 3 | 9.95 | 9.949999809 | 9.949999809 | A |
| 4 | 288.00 | 287.999996186 | 287.999996186 | A |
| 5 | 239.94 | 239.939994812 | 239.939994812 | A |

### `mart_daily_revenue.average_order_value`

money_type(); delta in dollars, at cents. Rows 2773; cents differ 42; raw differs 42. identical 2731, A 0, B 42, C 0; L9 = BQ exactly on 2773 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/marts/mart_daily_revenue.sql:11: cast(round(gross_revenue / nullif(order_count, 0), 2) as {{ money_type() }}) as average_order_value,`. C verdict: **no C rows**.

delta → rows: `-0.01` → 37, `0.00` → 2731, `0.01` → 5

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 2019-02-26 | 21.49 | 21.480000000 | 21.480000000 | B |
| 2019-03-15 | 36.65 | 36.640000000 | 36.640000000 | B |
| 2019-03-24 | 68.75 | 68.740000000 | 68.740000000 | B |
| 2019-03-28 | 18.98 | 18.970000000 | 18.970000000 | B |
| 2019-04-24 | 155.00 | 154.990000000 | 154.990000000 | B |

### `mart_daily_revenue.gross_margin`

money_type(); delta in dollars, at cents. Rows 2773; cents differ 2125; raw differs 2773. identical 0, A 648, B 2125, C 0; L9 = BQ exactly on 2773 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/marts/mart_daily_revenue.sql:10: gross_margin,`. C verdict: **no C rows**.

delta → rows: `-0.12` → 1, `-0.09` → 1, `-0.08` → 3, `-0.07` → 6, `-0.06` → 13, `-0.05` → 10, `-0.04` → 42, `-0.03` → 94, `-0.02` → 200, `-0.01` → 432, `0.00` → 648, `0.01` → 492, `0.02` → 309, `0.03` → 199, `0.04` → 112, `0.05` → 78, `0.06` → 42, `0.07` → 33, `0.08` → 14, `0.09` → 23, `0.10` → 7, `0.11` → 7, `0.12` → 2, `0.14` → 2, `0.16` → 1, `0.26` → 1, `0.43` → 1

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 2019-01-10 | 65.99 | 65.983120470 | 65.983120470 | B |
| 2019-01-30 | 58.57 | 58.562250446 | 58.562250446 | B |
| 2019-02-15 | 151.27 | 151.262809748 | 151.262809748 | B |
| 2019-02-24 | 71.30 | 71.307440417 | 71.307440417 | B |
| 2019-03-08 | 109.57 | 109.577882325 | 109.577882325 | B |

### `mart_daily_revenue.gross_revenue`

money_type(); delta in dollars, at cents. Rows 2773; cents differ 0; raw differs 2732. identical 41, A 2732, B 0, C 0; L9 = BQ exactly on 2773 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/marts/mart_daily_revenue.sql:8: gross_revenue,`. C verdict: **no C rows**.

delta → rows: `0.00` → 2773

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 2019-01-10 | 114.78 | 114.780000687 | 114.780000687 | A |
| 2019-01-12 | 135.77 | 135.769998550 | 135.769998550 | A |
| 2019-01-17 | 33.98 | 33.979999542 | 33.979999542 | A |
| 2019-01-26 | 190.94 | 190.940006256 | 190.940006256 | A |
| 2019-01-30 | 116.45 | 116.450000763 | 116.450000763 | A |

### `mart_daily_revenue.total_cost`

money_type(); delta in dollars, at cents. Rows 2773; cents differ 2124; raw differs 2773. identical 0, A 649, B 2124, C 0; L9 = BQ exactly on 2773 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/marts/mart_daily_revenue.sql:9: total_cost,`. C verdict: **no C rows**.

delta → rows: `-0.43` → 1, `-0.26` → 1, `-0.16` → 1, `-0.14` → 2, `-0.12` → 2, `-0.11` → 7, `-0.10` → 7, `-0.09` → 23, `-0.08` → 14, `-0.07` → 33, `-0.06` → 42, `-0.05` → 77, `-0.04` → 112, `-0.03` → 200, `-0.02` → 309, `-0.01` → 491, `0.00` → 649, `0.01` → 432, `0.02` → 200, `0.03` → 94, `0.04` → 43, `0.05` → 9, `0.06` → 13, `0.07` → 6, `0.08` → 3, `0.09` → 1, `0.12` → 1

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 2019-01-10 | 48.79 | 48.796880217 | 48.796880217 | B |
| 2019-01-30 | 57.88 | 57.887750317 | 57.887750317 | B |
| 2019-02-15 | 152.48 | 152.487190252 | 152.487190252 | B |
| 2019-02-24 | 60.22 | 60.212560041 | 60.212560041 | B |
| 2019-03-08 | 82.61 | 82.602121794 | 82.602121794 | B |

### `mart_product_performance.gross_margin`

money_type(); delta in dollars, at cents. Rows 29120; cents differ 21107; raw differs 28969. identical 151, A 7862, B 21107, C 0; L9 = BQ exactly on 29120 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/marts/mart_product_performance.sql:42: sales.gross_margin,`. C verdict: **no C rows**.

delta → rows: `-0.08` → 3, `-0.07` → 15, `-0.06` → 60, `-0.05` → 248, `-0.04` → 833, `-0.03` → 1813, `-0.02` → 3171, `-0.01` → 4056, `0.00` → 8013, `0.01` → 4034, `0.02` → 3455, `0.03` → 2050, `0.04` → 971, `0.05` → 303, `0.06` → 78, `0.07` → 14, `0.08` → 3

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 1 | 153.65 | 153.664000588 | 153.664000588 | B |
| 2 | 65.74 | 65.747000162 | 65.747000162 | B |
| 3 | 171.00 | 170.970000840 | 170.970000840 | B |
| 4 | 305.22 | 305.208000540 | 305.208000540 | B |
| 5 | 249.84 | 249.852000774 | 249.852000774 | B |

### `mart_product_performance.gross_margin_rate`

float_type(), compared at 1e-6 (round(x*1e6)::BIGINT); delta in 1e-6 units. Rows 29120; cents differ 24570; raw differs 28963. identical 157, A 4393, B 24570, C 0; L9 = BQ exactly on 29120 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/marts/mart_product_performance.sql:43: {{ safe_divide('sales.gross_margin', 'sales.gross_revenue') }}      as gross_margin_rate,`. C verdict: **no C rows**.

delta → rows: `-3159` → 1, `-2061` → 1, `-1857` → 1, `-1661` → 1, `-1360` → 1, `-1353` → 1, `-1286` → 1, `-1194` → 1, `-1143` → 1, `-1128` → 1, `-1068` → 1, `-1060` → 1, `-1000` → 3, `-989` → 1, `-949` → 1, `-947` → 1, `-911` → 1, `-906` → 1, `-885` → 1, `-876` → 1, `-873` → 1, `-859` → 1, `-852` → 1, `-846` → 1, `-830` → 1, `-829` → 1, `-814` → 1, `-813` → 1, `-807` → 1, `-797` → 1, `-770` → 1, `-769` → 1, `-741` → 1, `-737` → 1, `-734` → 1, `-727` → 1, `-726` → 1, `-722` → 1, `-718` → 1, `-714` → 3, `-713` → 1, `-712` → 1, `-700` → 1, `-692` → 2, `-681` → 1, `-673` → 1, `-669` → 1, `-667` → 2, `-658` → 1, `-651` → 1, `-644` → 1, `-643` → 1, `-638` → 1, `-626` → 2, `-620` → 2, `-615` → 1, `-613` → 1, `-610` → 1, `-609` → 1, `-603` → 1, `-601` → 1, `-596` → 1, `-595` → 1, `-593` → 2, `-587` → 1, `-581` → 3, `-580` → 1, `-579` → 1, `-576` → 1, `-571` → 1, `-568` → 1, `-567` → 1, `-563` → 1, `-561` → 1, `-559` → 1, `-558` → 1, `-556` → 2, `-553` → 1, `-544` → 2, `-543` → 1, `-542` → 1, `-541` → 1, `-536` → 1, `-533` → 2, `-531` → 3, `-530` → 1, `-529` → 3, `-528` → 2, `-526` → 1, `-525` → 1, `-524` → 2, `-519` → 1, `-517` → 1, `-516` → 1, `-515` → 1, `-514` → 1, `-512` → 2, `-510` → 1, `-509` → 3, `-508` → 4, `-506` → 1, `-505` → 1, `-504` → 1, `-501` → 2, `-500` → 7, `-499` → 2, `-498` → 1, `-496` → 1, `-495` → 2, `-493` → 1, `-491` → 2, `-490` → 1, `-489` → 1, `-488` → 1, `-486` → 1, `-485` → 4, `-484` → 1, `-483` → 1, `-482` → 1, `-481` → 3, `-480` → 1, `-479` → 1, `-478` → 1, `-477` → 1, `-476` → 2, `-475` → 1, `-474` → 1, `-470` → 1, `-469` → 2, `-468` → 2, `-467` → 1, `-465` → 4, `-464` → 2, `-462` → 4, `-460` → 2, `-459` → 1, `-458` → 1, `-456` → 4, `-455` → 4, `-454` → 1, `-452` → 1, `-451` → 2, `-450` → 1, `-449` → 2, `-448` → 1, `-446` → 1, `-445` → 1, `-444` → 5, `-443` → 4, `-442` → 4, `-441` → 2, `-440` → 1, `-438` → 1, `-437` → 1, `-436` → 1, `-435` → 1, `-433` → 1, `-432` → 1, `-431` → 2, `-430` → 1, `-429` → 9, `-428` → 2, `-427` → 3, `-426` → 1, `-424` → 1, `-422` → 1, `-421` → 3, `-420` → 1, `-419` → 4, `-417` → 1, `-415` → 1, `-414` → 2, `-413` → 2, `-412` → 2, `-409` → 2, `-408` → 1, `-407` → 2, `-406` → 2, `-405` → 1, `-404` → 2, `-403` → 3, `-402` → 2, `-401` → 2, `-400` → 3, `-399` → 3, `-398` → 2, `-397` → 1, `-396` → 2, `-395` → 4, `-393` → 4, `-392` → 1, `-391` → 5, `-390` → 1, `-388` → 1, `-387` → 2, `-385` → 7, `-384` → 3, `-383` → 1, `-382` → 2, `-381` → 2, `-380` → 2, `-379` → 1, `-378` → 3, `-377` → 1, `-376` → 1, `-375` → 3, `-374` → 1, `-373` → 3, `-372` → 5, `-371` → 1, `-370` → 2, `-369` → 1, `-368` → 5, `-367` → 1, `-366` → 1, `-365` → 3, `-364` → 7, `-363` → 2, `-362` → 4, `-361` → 2, `-360` → 1, `-359` → 2, `-358` → 2, `-357` → 3, `-356` → 7, `-355` → 3, `-354` → 2, `-353` → 1, `-352` → 3, `-351` → 1, `-350` → 4, `-349` → 2, `-348` → 2, `-347` → 1, `-346` → 5, `-345` → 3, `-344` → 5, `-343` → 3, `-342` → 2, `-341` → 2, `-339` → 3, `-338` → 2, `-337` → 3, `-336` → 3, `-335` → 4, `-334` → 8, `-333` → 92, `-332` → 3, `-331` → 4, `-330` → 3, `-329` → 1, `-328` → 2, `-327` → 1, `-326` → 3, `-325` → 2, `-324` → 2, `-323` → 4, `-322` → 3, `-321` → 4, `-320` → 2, `-319` → 6, `-318` → 1, `-316` → 5, `-315` → 4, `-314` → 4, `-313` → 5, `-312` → 4, `-310` → 5, `-308` → 12, `-307` → 2, `-306` → 5, `-305` → 2, `-304` → 5, `-303` → 9, `-302` → 3, `-301` → 1, `-300` → 4, `-299` → 4, `-298` → 2, `-297` → 4, `-296` → 7, `-295` → 2, `-294` → 4, `-293` → 4, `-292` → 3, `-291` → 6, `-290` → 6, `-289` → 6, `-288` → 6, `-287` → 2, `-286` → 31, `-285` → 2, `-284` → 5, `-283` → 5, `-282` → 2, `-281` → 2, `-280` → 2, `-279` → 9, `-278` → 10, `-277` → 2, `-276` → 5, `-275` → 5, `-274` → 3, `-273` → 13, `-272` → 2, `-271` → 4, `-270` → 9, `-269` → 3, `-268` → 4, `-267` → 7, `-266` → 8, `-265` → 4, `-264` → 4, `-263` → 8, `-262` → 3, `-261` → 4, `-260` → 9, `-259` → 11, `-258` → 5, `-257` → 5, `-256` → 7, `-255` → 4, `-254` → 5, `-253` → 7, `-252` → 5, `-251` → 4, `-250` → 34, `-249` → 9, `-248` → 5, `-247` → 9, `-246` → 5, `-245` → 3, `-244` → 4, `-243` → 9, `-242` → 7, `-241` → 15, `-240` → 9, `-239` → 17, `-238` → 10, `-237` → 11, `-236` → 7, `-235` → 15, `-234` → 8, `-233` → 5, `-232` → 6, `-231` → 15, `-230` → 9, `-229` → 6, `-228` → 9, `-227` → 7, `-226` → 7, `-225` → 14, `-224` → 15, `-223` → 11, `-222` → 47, `-221` → 7, `-220` → 13, `-219` → 6, `-218` → 7, `-217` → 11, `-216` → 8, `-215` → 8, `-214` → 10, `-213` → 13, `-212` → 9, `-211` → 18, `-210` → 7, `-209` → 4, `-208` → 5, `-207` → 12, `-206` → 9, `-205` → 9, `-204` → 13, `-203` → 11, `-202` → 6, `-201` → 11, `-200` → 246, `-199` → 10, `-198` → 17, `-197` → 7, `-196` → 10, `-195` → 10, `-194` → 14, `-193` → 10, `-192` → 14, `-191` → 13, `-190` → 19, `-189` → 12, `-188` → 12, `-187` → 10, `-186` → 15, `-185` → 18, `-184` → 14, `-183` → 9, `-182` → 46, `-181` → 13, `-180` → 7, `-179` → 6, `-178` → 11, `-177` → 10, `-176` → 23, `-175` → 10, `-174` → 14, `-173` → 10, `-172` → 15, `-171` → 11, `-170` → 18, `-169` → 9, `-168` → 15, `-167` → 91, `-166` → 22, `-165` → 10, `-164` → 21, `-163` → 18, `-162` → 21, `-161` → 21, `-160` → 17, `-159` → 12, `-158` → 19, `-157` → 14, `-156` → 27, `-155` → 23, `-154` → 45, `-153` → 10, `-152` → 20, `-151` → 19, `-150` → 25, `-149` → 17, `-148` → 22, `-147` → 23, `-146` → 26, `-145` → 17, `-144` → 16, `-143` → 131, `-142` → 22, `-141` → 22, `-140` → 29, `-139` → 18, `-138` → 34, `-137` → 15, `-136` → 20, `-135` → 18, `-134` → 16, `-133` → 23, `-132` → 17, `-131` → 20, `-130` → 27, `-129` → 17, `-128` → 26, `-127` → 23, `-126` → 14, `-125` → 75, `-124` → 27, `-123` → 31, `-122` → 40, `-121` → 43, `-120` → 34, `-119` → 22, `-118` → 69, `-117` → 27, `-116` → 31, `-115` → 26, `-114` → 41, `-113` → 29, `-112` → 42, `-111` → 158, `-110` → 30, `-109` → 27, `-108` → 29, `-107` → 31, `-106` → 34, `-105` → 58, `-104` → 33, `-103` → 42, `-102` → 30, `-101` → 50, `-100` → 32, `-99` → 30, `-98` → 29, `-97` → 35, `-96` → 34, `-95` → 77, `-94` → 37, `-93` → 36, `-92` → 28, `-91` → 140, `-90` → 24, `-89` → 43, `-88` → 33, `-87` → 68, `-86` → 27, `-85` → 46, `-84` → 32, `-83` → 86, `-82` → 56, `-81` → 47, `-80` → 36, `-79` → 43, `-78` → 38, `-77` → 125, `-76` → 49, `-75` → 28, `-74` → 72, `-73` → 40, `-72` → 45, `-71` → 97, `-70` → 37, `-69` → 59, `-68` → 62, `-67` → 75, `-66` → 30, `-65` → 55, `-64` → 44, `-63` → 132, `-62` → 43, `-61` → 71, `-60` → 43, `-59` → 117, `-58` → 62, `-57` → 48, `-56` → 101, `-55` → 33, `-54` → 61, `-53` → 98, `-52` → 44, `-51` → 132, `-50` → 74, `-49` → 51, `-48` → 121, `-47` → 62, `-46` → 44, `-45` → 119, `-44` → 41, `-43` → 130, `-42` → 106, `-41` → 95, `-40` → 107, `-39` → 65, `-38` → 91, `-37` → 112, `-36` → 79, `-35` → 74, `-34` → 146, `-33` → 60, `-32` → 85, `-31` → 86, `-30` → 131, `-29` → 131, `-28` → 112, `-27` → 90, `-26` → 113, `-25` → 108, `-24` → 100, `-23` → 115, `-22` → 106, `-21` → 91, `-20` → 160, `-19` → 111, `-18` → 89, `-17` → 112, `-16` → 110, `-15` → 88, `-14` → 128, `-13` → 130, `-12` → 93, `-11` → 106, `-10` → 110, `-9` → 83, `-8` → 113, `-7` → 90, `-6` → 120, `-5` → 89, `-4` → 78, `-3` → 66, `-2` → 69, `-1` → 69, `0` → 4484, `1` → 75, `2` → 59, `3` → 82, `4` → 93, `5` → 99, `6` → 94, `7` → 78, `8` → 102, `9` → 104, `10` → 135, `11` → 132, `12` → 83, `13` → 139, `14` → 115, `15` → 88, `16` → 119, `17` → 120, `18` → 106, `19` → 104, `20` → 176, `21` → 79, `22` → 113, `23` → 118, `24` → 105, `25` → 114, `26` → 121, `27` → 90, `28` → 93, `29` → 142, `30` → 110, `31` → 97, `32` → 101, `33` → 64, `34` → 174, `35` → 69, `36` → 72, `37` → 120, `38` → 108, `39` → 57, `40` → 102, `41` → 119, `42` → 111, `43` → 121, `44` → 81, `45` → 112, `46` → 66, `47` → 40, `48` → 105, `49` → 60, `50` → 85, `51` → 131, `52` → 51, `53` → 107, `54` → 65, `55` → 55, `56` → 97, `57` → 54, `58` → 73, `59` → 147, `60` → 61, `61` → 99, `62` → 88, `63` → 72, `64` → 34, `65` → 68, `66` → 40, `67` → 84, `68` → 42, `69` → 73, `70` → 50, `71` → 119, `72` → 48, `73` → 41, `74` → 56, `75` → 26, `76` → 50, `77` → 155, `78` → 35, `79` → 38, `80` → 48, `81` → 51, `82` → 54, `83` → 135, `84` → 47, `85` → 65, `86` → 29, `87` → 67, `88` → 47, `89` → 38, `90` → 40, `91` → 190, `92` → 30, `93` → 27, `94` → 31, `95` → 59, `96` → 43, `97` → 25, `98` → 39, `99` → 37, `100` → 36, `101` → 41, `102` → 32, `103` → 36, `104` → 41, `105` → 70, `106` → 20, `107` → 27, `108` → 31, `109` → 36, `110` → 29, `111` → 177, `112` → 32, `113` → 30, `114` → 34, `115` → 23, `116` → 33, `117` → 21, `118` → 54, `119` → 23, `120` → 39, `121` → 38, `122` → 28, `123` → 36, `124` → 33, `125` → 71, `126` → 16, `127` → 26, `128` → 23, `129` → 20, `130` → 34, `131` → 26, `132` → 20, `133` → 15, `134` → 24, `135` → 16, `136` → 24, `137` → 26, `138` → 24, `139` → 32, `140` → 19, `141` → 17, `142` → 25, `143` → 133, `144` → 20, `145` → 28, `146` → 18, `147` → 27, `148` → 28, `149` → 20, `150` → 11, `151` → 14, `152` → 24, `153` → 14, `154` → 30, `155` → 16, `156` → 9, `157` → 19, `158` → 18, `159` → 16, `160` → 11, `161` → 13, `162` → 30, `163` → 12, `164` → 24, `165` → 16, `166` → 20, `167` → 65, `168` → 13, `169` → 16, `170` → 13, `171` → 9, `172` → 24, `173` → 8, `174` → 16, `175` → 10, `176` → 19, `177` → 17, `178` → 13, `179` → 12, `180` → 13, `181` → 10, `182` → 50, `183` → 10, `184` → 14, `185` → 12, `186` → 10, `187` → 7, `188` → 16, `189` → 5, `190` → 24, `191` → 14, `192` → 8, `193` → 9, `194` → 10, `195` → 12, `196` → 15, `197` → 12, `198` → 9, `199` → 11, `200` → 311, `201` → 10, `202` → 12, `203` → 8, `204` → 14, `205` → 21, `206` → 16, `207` → 10, `208` → 9, `209` → 8, `210` → 13, `211` → 9, `212` → 11, `213` → 18, `214` → 12, `215` → 9, `216` → 14, `217` → 16, `218` → 5, `219` → 12, `220` → 6, `221` → 7, `222` → 46, `223` → 11, `224` → 6, `225` → 6, `226` → 7, `227` → 9, `228` → 9, `229` → 9, `230` → 8, `231` → 15, `232` → 5, `233` → 11, `234` → 3, `235` → 8, `236` → 9, `237` → 7, `238` → 5, `239` → 11, `240` → 5, `241` → 11, `242` → 7, `243` → 14, `244` → 9, `245` → 10, `246` → 10, `247` → 10, `248` → 5, `249` → 9, `250` → 27, `251` → 7, `252` → 6, `253` → 3, `254` → 4, `255` → 9, `256` → 7, `257` → 2, `258` → 4, `259` → 5, `260` → 2, `261` → 2, `262` → 5, `263` → 12, `264` → 12, `265` → 4, `266` → 5, `267` → 3, `268` → 7, `269` → 7, `270` → 7, `271` → 4, `272` → 6, `273` → 6, `274` → 10, `275` → 4, `276` → 6, `277` → 7, `278` → 4, `279` → 8, `280` → 7, `281` → 1, `282` → 1, `283` → 2, `284` → 6, `285` → 4, `286` → 34, `287` → 7, `288` → 4, `289` → 3, `290` → 8, `291` → 6, `292` → 6, `293` → 8, `294` → 4, `295` → 4, `296` → 2, `297` → 5, `298` → 7, `299` → 3, `300` → 5, `301` → 4, `302` → 7, `303` → 2, `304` → 5, `305` → 3, `306` → 6, `307` → 4, `308` → 12, `309` → 4, `310` → 5, `311` → 3, `312` → 2, `313` → 2, `314` → 5, `315` → 4, `316` → 4, `317` → 1, `318` → 5, `319` → 3, `320` → 2, `321` → 4, `322` → 2, `323` → 4, `324` → 5, `325` → 2, `326` → 3, `327` → 2, `328` → 2, `329` → 4, `330` → 1, `331` → 2, `333` → 93, `334` → 3, `335` → 2, `336` → 5, `337` → 1, `338` → 1, `339` → 6, `340` → 2, `341` → 2, `342` → 2, `343` → 1, `344` → 1, `346` → 3, `347` → 3, `350` → 1, `351` → 1, `352` → 4, `353` → 3, `354` → 5, `355` → 7, `356` → 1, `357` → 1, `358` → 2, `359` → 2, `360` → 5, `361` → 1, `362` → 6, `363` → 2, `364` → 9, `365` → 1, `366` → 2, `367` → 3, `368` → 1, `369` → 3, `370` → 4, `371` → 1, `372` → 4, `373` → 2, `374` → 3, `375` → 5, `377` → 6, `378` → 3, `379` → 3, `380` → 1, `381` → 5, `382` → 1, `383` → 2, `384` → 4, `385` → 8, `387` → 4, `388` → 3, `389` → 4, `390` → 5, `391` → 6, `392` → 3, `393` → 3, `394` → 1, `396` → 1, `397` → 2, `398` → 1, `399` → 1, `400` → 11, `404` → 2, `405` → 5, `406` → 1, `407` → 2, `408` → 2, `410` → 1, `411` → 2, `412` → 2, `413` → 3, `414` → 1, `415` → 1, `416` → 1, `417` → 3, `418` → 1, `419` → 4, `420` → 1, `421` → 4, `422` → 2, `423` → 2, `424` → 2, `425` → 2, `427` → 3, `428` → 2, `429` → 10, `430` → 4, `431` → 2, `432` → 4, `433` → 3, `434` → 3, `435` → 2, `437` → 2, `439` → 1, `440` → 1, `442` → 3, `443` → 2, `444` → 5, `445` → 1, `446` → 1, `447` → 1, `448` → 3, `451` → 1, `452` → 1, `454` → 2, `455` → 3, `456` → 1, `457` → 1, `458` → 2, `460` → 1, `462` → 4, `464` → 1, `467` → 3, `468` → 2, `469` → 2, `471` → 1, `472` → 2, `474` → 4, `478` → 2, `480` → 1, `482` → 1, `483` → 3, `484` → 1, `485` → 2, `486` → 2, `487` → 1, `488` → 2, `489` → 3, `490` → 1, `491` → 4, `492` → 2, `493` → 1, `494` → 2, `495` → 1, `496` → 1, `497` → 4, `498` → 1, `499` → 2, `500` → 6, `501` → 2, `502` → 1, `503` → 1, `505` → 2, `508` → 2, `509` → 1, `511` → 2, `512` → 4, `514` → 1, `516` → 2, `518` → 1, `519` → 1, `523` → 1, `524` → 1, `525` → 1, `526` → 2, `534` → 1, `536` → 1, `537` → 1, `538` → 1, `542` → 4, `543` → 1, `544` → 1, `545` → 2, `548` → 2, `553` → 1, `555` → 1, `556` → 2, `560` → 1, `562` → 1, `571` → 3, `572` → 1, `573` → 1, `576` → 1, `577` → 1, `592` → 1, `593` → 1, `594` → 1, `595` → 1, `596` → 1, `599` → 1, `600` → 1, `601` → 1, `607` → 1, `610` → 1, `614` → 1, `615` → 1, `616` → 1, `622` → 1, `626` → 1, `634` → 1, `636` → 2, `641` → 1, `646` → 1, `648` → 1, `652` → 1, `657` → 1, `660` → 1, `664` → 1, `667` → 4, `669` → 1, `673` → 1, `677` → 2, `678` → 1, `684` → 1, `689` → 1, `692` → 1, `693` → 1, `694` → 1, `702` → 1, `706` → 2, `712` → 1, `713` → 1, `718` → 1, `726` → 1, `746` → 1, `758` → 1, `769` → 1, `774` → 1, `785` → 1, `800` → 1, `811` → 1, `818` → 1, `821` → 1, `829` → 2, `831` → 1, `856` → 1, `858` → 1, `859` → 1, `865` → 1, `872` → 1, `884` → 1, `888` → 1, `965` → 1, `974` → 1, `977` → 1, `982` → 1, `983` → 1, `993` → 1, `1000` → 3, `1040` → 1, `1050` → 1, `1059` → 1, `1063` → 1, `1066` → 1, `1067` → 1, `1090` → 1, `1128` → 1, `1158` → 1, `1186` → 1, `1234` → 1, `1333` → 2, `1386` → 1, `1390` → 1, `1453` → 1, `1678` → 1, `1795` → 1, `1835` → 1, `2667` → 1, `2907` → 1, `5347` → 1, `85000` → 1, `NULL` → 66

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 1 | 0.44795918367346943 | 0.44800000171428567 | 0.44800000171428567 | B |
| 2 | 0.47294964028776976 | 0.47300000116546764 | 0.47300000116546764 | B |
| 3 | 0.41007194244604317 | 0.4100000020143885 | 0.4100000020143885 | B |
| 4 | 0.47101851851851856 | 0.4710000008333333 | 0.4710000008333333 | B |
| 5 | 0.4429787234042553 | 0.4430000013723404 | 0.4430000013723404 | B |

### `mart_product_performance.gross_revenue`

money_type(); delta in dollars, at cents. Rows 29120; cents differ 0; raw differs 15640. identical 13480, A 15640, B 0, C 0; L9 = BQ exactly on 29120 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/marts/mart_product_performance.sql:40: sales.gross_revenue,`. C verdict: **no C rows**.

delta → rows: `0.00` → 29120

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 13 | 383.50 | 383.499984740 | 383.499984740 | A |
| 16 | 164.75 | 164.750003815 | 164.750003815 | A |
| 20 | 317.00 | 317.000007630 | 317.000007630 | A |
| 28 | 301.98 | 301.980010986 | 301.980010986 | A |
| 31 | 289.75 | 289.750003815 | 289.750003815 | A |

### `mart_product_performance.retail_price`

money_type(); delta in dollars, at cents. Rows 29120; cents differ 0; raw differs 15675. identical 13445, A 15675, B 0, C 0; L9 = BQ exactly on 29120 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: direct cast, `models/marts/mart_product_performance.sql:38: products.retail_price,`; source `thelook_ecommerce.products.retail_price`, checked on every row: {'n': 29120, 'l2_not_cast': 0, 'l9_not_cast': 0, 'bq_not_cast9': 0}. C verdict: **no C rows**.

delta → rows: `0.00` → 29120

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 13 | 76.70 | 76.699996948 | 76.699996948 | A |
| 16 | 32.95 | 32.950000763 | 32.950000763 | A |
| 20 | 63.40 | 63.400001526 | 63.400001526 | A |
| 28 | 150.99 | 150.990005493 | 150.990005493 | A |
| 31 | 57.95 | 57.950000763 | 57.950000763 | A |

### `mart_product_performance.total_cost`

money_type(); delta in dollars, at cents. Rows 29120; cents differ 21107; raw differs 28969. identical 151, A 7862, B 21107, C 0; L9 = BQ exactly on 29120 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: derived, `models/marts/mart_product_performance.sql:41: sales.total_cost,`. C verdict: **no C rows**.

delta → rows: `-0.08` → 3, `-0.07` → 14, `-0.06` → 78, `-0.05` → 300, `-0.04` → 965, `-0.03` → 2052, `-0.02` → 3454, `-0.01` → 4043, `0.00` → 8013, `0.01` → 4059, `0.02` → 3173, `0.03` → 1812, `0.04` → 831, `0.05` → 245, `0.06` → 61, `0.07` → 14, `0.08` → 3

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 1 | 189.35 | 189.335999412 | 189.335999412 | B |
| 2 | 73.26 | 73.252999838 | 73.252999838 | B |
| 3 | 246.00 | 246.029999160 | 246.029999160 | B |
| 4 | 342.78 | 342.791999460 | 342.791999460 | B |
| 5 | 314.16 | 314.147999226 | 314.147999226 | B |

### `mart_product_performance.unit_cost`

money_type(); delta in dollars, at cents. Rows 29120; cents differ 1; raw differs 29035. identical 85, A 29034, B 1, C 0; L9 = BQ exactly on 29120 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: direct cast, `models/marts/mart_product_performance.sql:37: products.cost                                                       as unit_cost,`; source `thelook_ecommerce.products.cost`, checked on every row: {'n': 29120, 'l2_not_cast': 0, 'l9_not_cast': 0, 'bq_not_cast9': 0}. C verdict: **no C rows**.

delta → rows: `0.00` → 29119, `0.01` → 1

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 9500 | 6.64 | 6.645000000 | 6.645000000 | B |

### `stg_thelook__inventory_items.cost`

money_type(); delta in dollars, at cents. Rows 492226; cents differ 35; raw differs 490850. identical 1376, A 490815, B 35, C 0; L9 = BQ exactly on 492226 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: direct cast, `models/staging/stg_thelook__inventory_items.sql:15: cast(cost as {{ money_type() }})                    as cost,`; source `thelook_ecommerce.inventory_items.cost`, checked on every row: {'n': 492226, 'l2_not_cast': 0, 'l9_not_cast': 0, 'bq_not_cast9': 0}. C verdict: **no C rows**.

delta → rows: `0.00` → 492191, `0.01` → 35

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 3630 | 6.64 | 6.645000000 | 6.645000000 | B |
| 3631 | 6.64 | 6.645000000 | 6.645000000 | B |
| 7142 | 6.64 | 6.645000000 | 6.645000000 | B |
| 7143 | 6.64 | 6.645000000 | 6.645000000 | B |
| 7144 | 6.64 | 6.645000000 | 6.645000000 | B |

### `stg_thelook__inventory_items.product_retail_price`

money_type(); delta in dollars, at cents. Rows 492226; cents differ 0; raw differs 264590. identical 227636, A 264590, B 0, C 0; L9 = BQ exactly on 492226 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: direct cast, `models/staging/stg_thelook__inventory_items.sql:19: cast(product_retail_price as {{ money_type() }})    as product_retail_price,`; source `thelook_ecommerce.inventory_items.product_retail_price`, checked on every row: {'n': 492226, 'l2_not_cast': 0, 'l9_not_cast': 0, 'bq_not_cast9': 0}. C verdict: **no C rows**.

delta → rows: `0.00` → 492226

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 1 | 44.98 | 44.979999542 | 44.979999542 | A |
| 2 | 44.98 | 44.979999542 | 44.979999542 | A |
| 3 | 44.98 | 44.979999542 | 44.979999542 | A |
| 4 | 44.98 | 44.979999542 | 44.979999542 | A |
| 5 | 34.99 | 34.990001678 | 34.990001678 | A |

### `stg_thelook__order_items.sale_price`

money_type(); delta in dollars, at cents. Rows 182483; cents differ 0; raw differs 98069. identical 84414, A 98069, B 0, C 0; L9 = BQ exactly on 182483 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: direct cast, `models/staging/stg_thelook__order_items.sql:20: cast(sale_price as {{ money_type() }})    as sale_price`; source `thelook_ecommerce.order_items.sale_price`, checked on every row: {'n': 182483, 'l2_not_cast': 0, 'l9_not_cast': 0, 'bq_not_cast9': 0}. C verdict: **no C rows**.

delta → rows: `0.00` → 182483

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 1 | 44.98 | 44.979999542 | 44.979999542 | A |
| 2 | 34.99 | 34.990001678 | 34.990001678 | A |
| 5 | 49.94 | 49.939998627 | 49.939998627 | A |
| 6 | 39.95 | 39.950000763 | 39.950000763 | A |
| 7 | 21.99 | 21.989999771 | 21.989999771 | A |

### `stg_thelook__products.cost`

money_type(); delta in dollars, at cents. Rows 29120; cents differ 1; raw differs 29035. identical 85, A 29034, B 1, C 0; L9 = BQ exactly on 29120 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: direct cast, `models/staging/stg_thelook__products.sql:11: cast(cost as {{ money_type() }})            as cost,`; source `thelook_ecommerce.products.cost`, checked on every row: {'n': 29120, 'l2_not_cast': 0, 'l9_not_cast': 0, 'bq_not_cast9': 0}. C verdict: **no C rows**.

delta → rows: `0.00` → 29119, `0.01` → 1

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 9500 | 6.64 | 6.645000000 | 6.645000000 | B |

### `stg_thelook__products.retail_price`

money_type(); delta in dollars, at cents. Rows 29120; cents differ 0; raw differs 15675. identical 13445, A 15675, B 0, C 0; L9 = BQ exactly on 29120 rows. Invariants: identical+A+B+C=rows_compared holds, A+B+C=raw_differ holds, B+C=cents_differ holds.
Lineage: direct cast, `models/staging/stg_thelook__products.sql:15: cast(retail_price as {{ money_type() }})    as retail_price,`; source `thelook_ecommerce.products.retail_price`, checked on every row: {'n': 29120, 'l2_not_cast': 0, 'l9_not_cast': 0, 'bq_not_cast9': 0}. C verdict: **no C rows**.

delta → rows: `0.00` → 29120

| key | l2 | l9 | bq | bucket |
|---|---|---|---|---|
| 13 | 76.70 | 76.699996948 | 76.699996948 | A |
| 16 | 32.95 | 32.950000763 | 32.950000763 | A |
| 20 | 63.40 | 63.400001526 | 63.400001526 | A |
| 28 | 150.99 | 150.990005493 | 150.990005493 | A |
| 31 | 57.95 | 57.950000763 | 57.950000763 | A |

## Where L9 is not BigQuery

`mart_customer_summary.average_order_value`: 7 rows (`models/marts/mart_customer_summary.sql:39: cast(round(users.lifetime_gross_revenue / nullif(users.lifetime_orders, 0), 2) as {{ money_type() }})                                      as average_order_value,`). Their buckets (decided by L2 against BigQuery; L9 only separates B from C): identical 7, A 0, B 0, C 0.

| key | numerator_l9 | numerator_bq | numerator_l2 | l2_double_quotient | denominator | duckdb_double_quotient | numeric_quotient_9dp | duckdb_cents | numeric_rule_cents | l2 | l9 | bq | division_rule_explains |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 34544 | 191.249999999 | 191.249999999 | 191.25 | 95.625 | 2 | 95.6249999995 | 95.625000000 | 95.62 | 95.63 | 95.63 | 95.620000000 | 95.630000000 | True |
| 51071 | 669.499999999 | 669.499999999 | 669.50 | 167.375 | 4 | 167.37499999975 | 167.375000000 | 167.37 | 167.38 | 167.38 | 167.370000000 | 167.380000000 | True |
| 55516 | 304.249999999 | 304.249999999 | 304.25 | 152.125 | 2 | 152.1249999995 | 152.125000000 | 152.12 | 152.13 | 152.13 | 152.120000000 | 152.130000000 | True |
| 61817 | 136.499999999 | 136.499999999 | 136.50 | 34.125 | 4 | 34.12499999975 | 34.125000000 | 34.12 | 34.13 | 34.13 | 34.120000000 | 34.130000000 | True |
| 66722 | 296.499999999 | 296.499999999 | 296.50 | 74.125 | 4 | 74.12499999975 | 74.125000000 | 74.12 | 74.13 | 74.13 | 74.120000000 | 74.130000000 | True |
| 69968 | 212.749999999 | 212.749999999 | 212.75 | 106.375 | 2 | 106.3749999995 | 106.375000000 | 106.37 | 106.38 | 106.38 | 106.370000000 | 106.380000000 | True |
| 96501 | 289.499999999 | 289.499999999 | 289.50 | 72.375 | 4 | 72.37499999975 | 72.375000000 | 72.37 | 72.38 | 72.38 | 72.370000000 | 72.380000000 | True |

All 7 rows are `round(x / n, 2)` on a money value and an integer. The inputs are the same money on L9 and BigQuery, but the engines type the division differently: DuckDB `DECIMAL / BIGINT` is DOUBLE, so `round(95.6249999995, 2)` = 95.62; BigQuery `NUMERIC / INT64` is NUMERIC, so the quotient is first rounded to nine decimals (95.625000000) and then `ROUND(…, 2)` = 95.63. Recomputing both rules on every one of these rows reproduces L9 and BigQuery on 7 of 7 (`division_rule_explains`). L2 equals BigQuery on them because its numerator is already whole cents (`numerator_l2`), so its DOUBLE quotient is an exact half cent (`l2_double_quotient`) and rounds away from zero, as BigQuery's does.

## Base-value control (raw FLOAT64 in dev.duckdb)

Values whose cent differs between `cast(x as decimal(18,2))` (one rounding) and `round(cast(x as decimal(38,9)), 2)` (through nine decimals):

| source | n | changes | examples |
|---|---|---|---|
| products.cost | 29120 | 1 | 6.644999999552965 (1 rows: 6.64 vs 6.65) |
| products.retail_price | 29120 | 0 | None |
| order_items.sale_price | 182483 | 0 | None |
| inventory_items.cost | 492226 | 35 | 6.644999999552965 (35 rows: 6.64 vs 6.65) |
| inventory_items.product_retail_price | 492226 | 0 | None |

## The answer

Is there any row where the money is genuinely different money?

**No. 0 rows.** Of 273826 column-rows whose cents differ, 273826 are reproduced exactly by L9 (the declared scale, propagated).

## Proposal (unapplied)

Not applied: `macros/polyglot/types.sql` is unchanged. The one-line change that gives the DuckDB leg BigQuery's declared scale, exactly as L9 builds it:

```diff
diff --git a/macros/polyglot/types.sql b/target/row_join/project/macros/polyglot/types.sql
index 773bfd1..81dd55b 100644
--- a/macros/polyglot/types.sql
+++ b/target/row_join/project/macros/polyglot/types.sql
@@ -83,7 +83,7 @@
 {%- endmacro %}
 
 {% macro default__money_type() -%}
-    decimal(18,2)
+    decimal(38,9)
 {%- endmacro %}
 
 {% macro bigquery__money_type() -%}
```

What L9 proves about it: with this line, DuckDB's value equals BigQuery's exactly on 6605902 of 6605909 compared column-rows, which removes all 273826 cent differences (every one is B). It is not sufficient on its own: on the other 7 rows (`mart_customer_summary.average_order_value`) it would *create* a one-cent difference that the DuckDB leg does not have today (see Where L9 is not BigQuery); closing those needs the division itself to round to nine decimals before the cents on DuckDB. Applying it also changes every published DuckDB money value from 2 to 9 decimals.

## Reproduce

```
BQ_KEYFILE=<key> DBT_ENV=rows make value-parity   # the pair (analyses/value_parity/fresh/)
BQ_KEYFILE=<key> DBT_ENV=rows make row-join       # this report
```
