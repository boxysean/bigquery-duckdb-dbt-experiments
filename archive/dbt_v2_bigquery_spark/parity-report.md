# Parity report - Spark vs BigQuery

Generated 2026-10-07T01:20:48+0200 by `scripts/parity.py` (same-data gating: ON (default); Spark leg: `compiled`). Wall time 3599.8 s; BigQuery bytes billed 2,801,795,072.

## Verdict

**Exit 1: gating (names/types): none; rows/values: ['dim_distribution_centers', 'dim_products', 'dim_users', 'fct_inventory_items', 'fct_order_items', 'fct_orders', 'int_cohorts__user_months', 'int_inventory__by_product_center', 'int_inventory_items__enriched', 'int_order_items__enriched', 'int_orders__daily', 'int_orders__item_rollup', 'int_products__sales', 'int_users__lifetime_orders', 'mart_cohort_retention', 'mart_customer_summary', 'mart_daily_revenue', 'mart_product_performance', 'stg_thelook__inventory_items', 'stg_thelook__order_items', 'stg_thelook__products']**

* models matching on every check: **8 of 29**
* differing on names/types (gating): none
* differing on rows/values only: 21 (dim_distribution_centers, dim_products, dim_users, fct_inventory_items, fct_order_items, fct_orders, int_cohorts__user_months, int_inventory__by_product_center, int_inventory_items__enriched, int_order_items__enriched, int_orders__daily, int_orders__item_rollup, int_products__sales, int_users__lifetime_orders, mart_cohort_retention, mart_customer_summary, mart_daily_revenue, mart_product_performance, stg_thelook__inventory_items, stg_thelook__order_items, stg_thelook__products)
* not measured: none
* legs: Spark ok; BigQuery ok
* digest self-check: PASS
* same-data premise: 7 of 7 sources identical on every check

## The money prediction (SPEC 6)

Prediction: `money_type()` is `decimal(18,2)` on Spark - exact to its declared
scale, like the root project's DuckDB - and `NUMERIC` (nine decimals) on
BigQuery, so the same class of money difference the root project measured
between DuckDB and BigQuery should appear between Spark and BigQuery.

**Result: CONFIRMED.** 54 decimal column(s) differ row by row (of 54 decimal columns measured; 0 match exactly). Every differing column, joined on the model's primary key:

| model | column | key | differing rows | rows compared | Spark == BigQuery rounded to cents | max abs difference | example (key: spark / bigquery) |
|---|---|---|---|---|---|---|---|
| `dim_distribution_centers` | `open_inventory_value` | `distribution_center_id` | 10 | 10 | 0 | 8.898967913 | `2`: `1083957.18` / `1083954.762238527` |
| `dim_products` | `unit_cost` | `product_id` | 29,035 | 29,120 | 29,034 | 0.005 | `12131`: `20.48` / `20.484000005` |
| `dim_products` | `retail_price` | `product_id` | 15,675 | 29,120 | 15,675 | 0.000014648 | `2248`: `36.99` / `36.990001678` |
| `dim_products` | `gross_revenue` | `product_id` | 15,637 | 29,120 | 15,637 | 0.00013428 | `2248`: `369.9` / `369.90001678` |
| `dim_products` | `gross_margin` | `product_id` | 28,970 | 29,120 | 7,877 | 0.084998708 | `12131`: `108.64` / `108.611999965` |
| `dim_users` | `lifetime_gross_revenue` | `user_id` | 57,929 | 100,000 | 57,929 | 0.000021896 | `12131`: `58.95` / `58.950000763` |
| `dim_users` | `lifetime_gross_margin` | `user_id` | 79,911 | 100,000 | 64,563 | 0.029437656 | `12131`: `29.47` / `29.475000382` |
| `fct_inventory_items` | `unit_cost` | `inventory_item_id` | 486,407 | 487,799 | 486,378 | 0.005 | `297819`: `33.07` / `33.067759285` |
| `fct_inventory_items` | `product_retail_price` | `inventory_item_id` | 262,440 | 487,799 | 262,440 | 0.000014648 | `297819`: `77.99` / `77.989997864` |
| `fct_order_items` | `sale_price` | `order_item_id` | 97,201 | 180,778 | 97,201 | 0.000014648 | `12131`: `29.99` / `29.989999771` |
| `fct_order_items` | `product_cost` | `order_item_id` | 180,263 | 180,778 | 180,253 | 0.005 | `34095`: `96.48` / `96.479999721` |
| `fct_order_items` | `gross_margin` | `order_item_id` | 180,263 | 180,778 | 179,724 | 0.005002746 | `34095`: `83.52` / `83.520000279` |
| `fct_order_items` | `product_retail_price` | `order_item_id` | 97,201 | 180,778 | 97,201 | 0.000014648 | `12131`: `29.99` / `29.989999771` |
| `fct_orders` | `gross_revenue` | `order_id` | 77,895 | 124,650 | 77,895 | 0.000020294 | `34095`: `30.98` / `30.979999542` |
| `fct_orders` | `total_cost` | `order_id` | 124,394 | 124,650 | 113,643 | 0.01884975 | `34095`: `12.96` / `12.955629769` |
| `fct_orders` | `gross_margin` | `order_id` | 124,394 | 124,650 | 113,377 | 0.018849979 | `34095`: `18.02` / `18.024369773` |
| `int_cohorts__user_months` | `revenue` | `user_month_key` | 76,230 | 120,636 | 76,230 | 0.000020294 | `5423a6c9c360856d2be1029ccb534450`: `356.99` / `356.990005493` |
| `int_inventory__by_product_center` | `open_inventory_value` | `product_center_key` | 28,970 | 29,055 | 6,427 | 0.164997459 | `a1b9a3e0f9e4399c3ae59f5ba2bbc833`: `225.6` / `225.59999898` |
| `int_inventory__by_product_center` | `open_retail_value` | `product_center_key` | 15,637 | 29,055 | 15,637 | 0.000256347 | `634d563ff554bab38a34fbc9c6f97a4e`: `480.88` / `480.88000488` |
| `int_inventory_items__enriched` | `unit_cost` | `inventory_item_id` | 486,407 | 487,799 | 486,378 | 0.005 | `297819`: `33.07` / `33.067759285` |
| `int_inventory_items__enriched` | `product_retail_price` | `inventory_item_id` | 262,440 | 487,799 | 262,440 | 0.000014648 | `297819`: `77.99` / `77.989997864` |
| `int_order_items__enriched` | `sale_price` | `order_item_id` | 97,201 | 180,778 | 97,201 | 0.000014648 | `12131`: `29.99` / `29.989999771` |
| `int_order_items__enriched` | `product_cost` | `order_item_id` | 180,263 | 180,778 | 180,253 | 0.005 | `34095`: `96.48` / `96.479999721` |
| `int_order_items__enriched` | `gross_margin` | `order_item_id` | 180,263 | 180,778 | 179,724 | 0.005002746 | `34095`: `83.52` / `83.520000279` |
| `int_orders__daily` | `gross_revenue` | `order_date` | 2,738 | 2,779 | 2,738 | 0.000148133 | `2020-04-07`: `584.89` / `584.890001297` |
| `int_orders__daily` | `total_cost` | `order_date` | 2,776 | 2,779 | 661 | 0.406985847 | `2020-04-07`: `311.37` / `311.357701599` |
| `int_orders__daily` | `gross_margin` | `order_date` | 2,776 | 2,779 | 661 | 0.407096846 | `2020-04-07`: `273.52` / `273.532299698` |
| `int_orders__item_rollup` | `gross_revenue` | `order_id` | 77,895 | 124,650 | 77,895 | 0.000020294 | `34095`: `30.98` / `30.979999542` |
| `int_orders__item_rollup` | `total_cost` | `order_id` | 124,394 | 124,650 | 113,643 | 0.01884975 | `34095`: `12.96` / `12.955629769` |
| `int_orders__item_rollup` | `gross_margin` | `order_id` | 124,394 | 124,650 | 113,377 | 0.018849979 | `34095`: `18.02` / `18.024369773` |
| `int_products__sales` | `gross_revenue` | `product_id` | 15,637 | 29,120 | 15,637 | 0.00013428 | `2248`: `369.9` / `369.90001678` |
| `int_products__sales` | `total_cost` | `product_id` | 28,970 | 29,120 | 7,881 | 0.084998708 | `12131`: `143.36` / `143.388000035` |
| `int_products__sales` | `gross_margin` | `product_id` | 28,970 | 29,120 | 7,877 | 0.084998708 | `12131`: `108.64` / `108.611999965` |
| `int_users__lifetime_orders` | `lifetime_gross_revenue` | `user_id` | 57,929 | 100,000 | 57,929 | 0.000021896 | `12131`: `58.95` / `58.950000763` |
| `int_users__lifetime_orders` | `lifetime_total_cost` | `user_id` | 79,911 | 100,000 | 64,685 | 0.029441776 | `12131`: `29.48` / `29.475000381` |
| `int_users__lifetime_orders` | `lifetime_gross_margin` | `user_id` | 79,911 | 100,000 | 64,563 | 0.029437656 | `12131`: `29.47` / `29.475000382` |
| `mart_cohort_retention` | `revenue` | `cohort_activity_key` | 3,683 | 3,938 | 3,683 | 0.000382681 | `71ce817e4d62edb14d9a505f70b59259`: `102.99` / `102.989999771` |
| `mart_customer_summary` | `lifetime_gross_revenue` | `user_id` | 57,929 | 100,000 | 57,929 | 0.000021896 | `12131`: `58.95` / `58.950000763` |
| `mart_customer_summary` | `lifetime_gross_margin` | `user_id` | 79,911 | 100,000 | 64,563 | 0.029437656 | `12131`: `29.47` / `29.475000382` |
| `mart_customer_summary` | `average_order_value` | `user_id` | 5,443 | 100,000 | 0 | 0.01 | `80164`: `39.49` / `39.48` |
| `mart_daily_revenue` | `gross_revenue` | `revenue_date` | 2,738 | 2,779 | 2,738 | 0.000148133 | `2020-04-07`: `584.89` / `584.890001297` |
| `mart_daily_revenue` | `total_cost` | `revenue_date` | 2,776 | 2,779 | 661 | 0.406985847 | `2020-04-07`: `311.37` / `311.357701599` |
| `mart_daily_revenue` | `gross_margin` | `revenue_date` | 2,776 | 2,779 | 661 | 0.407096846 | `2020-04-07`: `273.52` / `273.532299698` |
| `mart_daily_revenue` | `average_order_value` | `revenue_date` | 43 | 2,779 | 0 | 0.01 | `2019-12-08`: `42.61` / `42.6` |
| `mart_product_performance` | `unit_cost` | `product_id` | 29,035 | 29,120 | 29,034 | 0.005 | `12131`: `20.48` / `20.484000005` |
| `mart_product_performance` | `retail_price` | `product_id` | 15,675 | 29,120 | 15,675 | 0.000014648 | `17453`: `75.56` / `75.559997559` |
| `mart_product_performance` | `gross_revenue` | `product_id` | 15,637 | 29,120 | 15,637 | 0.00013428 | `17453`: `377.8` / `377.799987795` |
| `mart_product_performance` | `total_cost` | `product_id` | 28,970 | 29,120 | 7,881 | 0.084998708 | `12131`: `143.36` / `143.388000035` |
| `mart_product_performance` | `gross_margin` | `product_id` | 28,970 | 29,120 | 7,877 | 0.084998708 | `12131`: `108.64` / `108.611999965` |
| `stg_thelook__inventory_items` | `cost` | `inventory_item_id` | 486,407 | 487,799 | 486,378 | 0.005 | `297819`: `33.07` / `33.067759285` |
| `stg_thelook__inventory_items` | `product_retail_price` | `inventory_item_id` | 262,440 | 487,799 | 262,440 | 0.000014648 | `297819`: `77.99` / `77.989997864` |
| `stg_thelook__order_items` | `sale_price` | `order_item_id` | 97,201 | 180,778 | 97,201 | 0.000014648 | `12131`: `29.99` / `29.989999771` |
| `stg_thelook__products` | `cost` | `product_id` | 29,035 | 29,120 | 29,034 | 0.005 | `12131`: `20.48` / `20.484000005` |
| `stg_thelook__products` | `retail_price` | `product_id` | 15,675 | 29,120 | 15,675 | 0.000014648 | `2248`: `36.99` / `36.990001678` |

Why: the source money columns are FLOAT64. BigQuery casts them to NUMERIC and
keeps nine decimals (`12.989999771`); Spark casts to `decimal(18,2)` and keeps
cents (`12.99`). Where the Spark value equals the BigQuery value rounded half-up
to cents, the difference is exactly that rounding; sums and averages of
rounded vs unrounded values then drift by more than half a cent.

<details><summary>Every decimal column and its raw types</summary>

| model | column | Spark raw type | BigQuery raw type | checksum equal |
|---|---|---|---|---|
| `dim_distribution_centers` | `open_inventory_value` | `decimal(18,2)` | `NUMERIC` | **no** |
| `dim_products` | `unit_cost` | `decimal(18,2)` | `NUMERIC` | **no** |
| `dim_products` | `retail_price` | `decimal(18,2)` | `NUMERIC` | **no** |
| `dim_products` | `gross_revenue` | `decimal(18,2)` | `NUMERIC` | **no** |
| `dim_products` | `gross_margin` | `decimal(18,2)` | `NUMERIC` | **no** |
| `dim_users` | `lifetime_gross_revenue` | `decimal(18,2)` | `NUMERIC` | **no** |
| `dim_users` | `lifetime_gross_margin` | `decimal(18,2)` | `NUMERIC` | **no** |
| `fct_inventory_items` | `unit_cost` | `decimal(18,2)` | `NUMERIC` | **no** |
| `fct_inventory_items` | `product_retail_price` | `decimal(18,2)` | `NUMERIC` | **no** |
| `fct_order_items` | `sale_price` | `decimal(18,2)` | `NUMERIC` | **no** |
| `fct_order_items` | `product_cost` | `decimal(18,2)` | `NUMERIC` | **no** |
| `fct_order_items` | `gross_margin` | `decimal(18,2)` | `NUMERIC` | **no** |
| `fct_order_items` | `product_retail_price` | `decimal(18,2)` | `NUMERIC` | **no** |
| `fct_orders` | `gross_revenue` | `decimal(18,2)` | `NUMERIC` | **no** |
| `fct_orders` | `total_cost` | `decimal(18,2)` | `NUMERIC` | **no** |
| `fct_orders` | `gross_margin` | `decimal(18,2)` | `NUMERIC` | **no** |
| `int_cohorts__user_months` | `revenue` | `decimal(18,2)` | `NUMERIC` | **no** |
| `int_inventory__by_product_center` | `open_inventory_value` | `decimal(18,2)` | `NUMERIC` | **no** |
| `int_inventory__by_product_center` | `open_retail_value` | `decimal(18,2)` | `NUMERIC` | **no** |
| `int_inventory_items__enriched` | `unit_cost` | `decimal(18,2)` | `NUMERIC` | **no** |
| `int_inventory_items__enriched` | `product_retail_price` | `decimal(18,2)` | `NUMERIC` | **no** |
| `int_order_items__enriched` | `sale_price` | `decimal(18,2)` | `NUMERIC` | **no** |
| `int_order_items__enriched` | `product_cost` | `decimal(18,2)` | `NUMERIC` | **no** |
| `int_order_items__enriched` | `gross_margin` | `decimal(18,2)` | `NUMERIC` | **no** |
| `int_orders__daily` | `gross_revenue` | `decimal(18,2)` | `NUMERIC` | **no** |
| `int_orders__daily` | `total_cost` | `decimal(18,2)` | `NUMERIC` | **no** |
| `int_orders__daily` | `gross_margin` | `decimal(18,2)` | `NUMERIC` | **no** |
| `int_orders__item_rollup` | `gross_revenue` | `decimal(18,2)` | `NUMERIC` | **no** |
| `int_orders__item_rollup` | `total_cost` | `decimal(18,2)` | `NUMERIC` | **no** |
| `int_orders__item_rollup` | `gross_margin` | `decimal(18,2)` | `NUMERIC` | **no** |
| `int_products__sales` | `gross_revenue` | `decimal(18,2)` | `NUMERIC` | **no** |
| `int_products__sales` | `total_cost` | `decimal(18,2)` | `NUMERIC` | **no** |
| `int_products__sales` | `gross_margin` | `decimal(18,2)` | `NUMERIC` | **no** |
| `int_users__lifetime_orders` | `lifetime_gross_revenue` | `decimal(18,2)` | `NUMERIC` | **no** |
| `int_users__lifetime_orders` | `lifetime_total_cost` | `decimal(18,2)` | `NUMERIC` | **no** |
| `int_users__lifetime_orders` | `lifetime_gross_margin` | `decimal(18,2)` | `NUMERIC` | **no** |
| `mart_cohort_retention` | `revenue` | `decimal(18,2)` | `NUMERIC` | **no** |
| `mart_customer_summary` | `lifetime_gross_revenue` | `decimal(18,2)` | `NUMERIC` | **no** |
| `mart_customer_summary` | `lifetime_gross_margin` | `decimal(18,2)` | `NUMERIC` | **no** |
| `mart_customer_summary` | `average_order_value` | `decimal(18,2)` | `NUMERIC` | **no** |
| `mart_daily_revenue` | `gross_revenue` | `decimal(18,2)` | `NUMERIC` | **no** |
| `mart_daily_revenue` | `total_cost` | `decimal(18,2)` | `NUMERIC` | **no** |
| `mart_daily_revenue` | `gross_margin` | `decimal(18,2)` | `NUMERIC` | **no** |
| `mart_daily_revenue` | `average_order_value` | `decimal(18,2)` | `NUMERIC` | **no** |
| `mart_product_performance` | `unit_cost` | `decimal(18,2)` | `NUMERIC` | **no** |
| `mart_product_performance` | `retail_price` | `decimal(18,2)` | `NUMERIC` | **no** |
| `mart_product_performance` | `gross_revenue` | `decimal(18,2)` | `NUMERIC` | **no** |
| `mart_product_performance` | `total_cost` | `decimal(18,2)` | `NUMERIC` | **no** |
| `mart_product_performance` | `gross_margin` | `decimal(18,2)` | `NUMERIC` | **no** |
| `stg_thelook__inventory_items` | `cost` | `decimal(18,2)` | `NUMERIC` | **no** |
| `stg_thelook__inventory_items` | `product_retail_price` | `decimal(18,2)` | `NUMERIC` | **no** |
| `stg_thelook__order_items` | `sale_price` | `decimal(18,2)` | `NUMERIC` | **no** |
| `stg_thelook__products` | `cost` | `decimal(18,2)` | `NUMERIC` | **no** |
| `stg_thelook__products` | `retail_price` | `decimal(18,2)` | `NUMERIC` | **no** |

</details>

## The same-data premise: sources

Spark reads the Parquet snapshot `scripts/load_spark_sources.py` pulled;
BigQuery reads `bigquery-public-data.thelook_ecommerce` live. If these differ,
model differences are drift, not the engines.

| table | rows spark | rows bigquery | cols | verdict | differences |
|---|---|---|---|---|---|
| `distribution_centers` | 10 | 10 | 5 | match | 0 |
| `products` | 29120 | 29120 | 9 | match | 0 |
| `users` | 100000 | 100000 | 16 | match | 0 |
| `inventory_items` | 487799 | 487799 | 12 | match | 0 |
| `orders` | 124650 | 124650 | 9 | match | 0 |
| `order_items` | 180778 | 180778 | 11 | match | 0 |
| `events` | 2421086 | 2421086 | 13 | match | 0 |

* `distribution_centers.distribution_center_geom` is GEOGRAPHY on BigQuery and WKT `string` on Spark (the loader carries it as text); compared as `ST_ASTEXT(x)` vs the string.
* `users.user_geom` is GEOGRAPHY on BigQuery and WKT `string` on Spark (the loader carries it as text); compared as `ST_ASTEXT(x)` vs the string.

## Digest self-check: PASS

Both engines render a fixture of constants (int, float, bool, date, timestamp,
string, decimal, array, struct, and an all-NULL row) through the production code
path - schema discovery, kind mapping, canonical text, md5 digest, SUM - and
every metric must be identical. The Spark session time zone must be UTC.

| metric | Spark | BigQuery |
|---|---|---|
| __rows | 7 | 7 |
| arr__distinct | 6 | 6 |
| arr__nulls | 1 | 1 |
| arr__sum | 11289685126 | 11289685126 |
| b__distinct | 2 | 2 |
| b__nulls | 1 | 1 |
| b__sum | 15531600020 | 15531600020 |
| d__distinct | 6 | 6 |
| d__nulls | 1 | 1 |
| d__sum | 12581459669 | 12581459669 |
| dec__distinct | 6 | 6 |
| dec__nulls | 1 | 1 |
| dec__sum | 16387773551 | 16387773551 |
| f__distinct | 6 | 6 |
| f__nulls | 1 | 1 |
| f__sum | 11690450866 | 11690450866 |
| i__distinct | 6 | 6 |
| i__nulls | 1 | 1 |
| i__sum | 17675302999 | 17675302999 |
| s__distinct | 6 | 6 |
| s__nulls | 1 | 1 |
| s__sum | 13135857637 | 13135857637 |
| st__distinct | 6 | 6 |
| st__nulls | 1 | 1 |
| st__sum | 13014484839 | 13014484839 |
| ts__distinct | 6 | 6 |
| ts__nulls | 1 | 1 |
| ts__sum | 12553943833 | 12553943833 |

| column | Spark kind (raw) | BigQuery kind (raw) |
|---|---|---|
| i | int64 (`bigint`) | int64 (`INTEGER`) |
| f | float64 (`double`) | float64 (`FLOAT`) |
| b | bool (`boolean`) | bool (`BOOLEAN`) |
| d | date (`date`) | date (`DATE`) |
| ts | timestamp (`timestamp`) | timestamp (`TIMESTAMP`) |
| s | string (`string`) | string (`STRING`) |
| dec | decimal (`decimal(18,2)`) | decimal (`NUMERIC`) |
| arr | array<int64> (`array<bigint>`) | array<int64> (`ARRAY<INTEGER>`) |
| st | struct<a:int64,b:string> (`struct<a:bigint,b:string>`) | struct<a:int64,b:string> (`STRUCT<a INTEGER, b STRING>`) |

Spark session time zone: `UTC`.

## Per model

| layer | model | rows spark | rows bigquery | cols | verdict | differences | spark s | bigquery s |
|---|---|---|---|---|---|---|---|---|
| marts | `dim_date` | 2825 | 2825 | 9 | match | 0 | 16.94 | 1.94 |
| marts | `dim_distribution_centers` | 10 | 10 | 8 | differs | 1 | 16.91 | 1.52 |
| marts | `dim_products` | 29120 | 29120 | 15 | differs | 7 | 41.98 | 2.06 |
| marts | `dim_users` | 100000 | 100000 | 20 | differs | 4 | 42.16 | 6.41 |
| marts | `fct_inventory_items` | 487799 | 487799 | 12 | differs | 3 | 45.67 | 8.35 |
| marts | `fct_order_items` | 180778 | 180778 | 21 | differs | 6 | 74.14 | 11.5 |
| marts | `fct_orders` | 124650 | 124650 | 15 | differs | 6 | 51.73 | 6.16 |
| marts | `mart_cohort_retention` | 3938 | 3938 | 8 | differs | 2 | 25.54 | 1.86 |
| marts | `mart_customer_summary` | 100000 | 100000 | 13 | differs | 6 | 36.52 | 7.03 |
| marts | `mart_daily_revenue` | 2779 | 2779 | 9 | differs | 8 | 36.2 | 1.41 |
| marts | `mart_product_performance` | 29120 | 29120 | 16 | differs | 11 | 35.1 | 2.22 |
| intermediate | `int_cohorts__user_months` | 120636 | 120636 | 7 | differs | 2 | 41.54 | 4.82 |
| intermediate | `int_events__sessions` | 680778 | 680778 | 10 | match | 0 | 50.77 | 5.76 |
| intermediate | `int_inventory__by_product_center` | 29055 | 29055 | 8 | differs | 4 | 38.08 | 1.72 |
| intermediate | `int_inventory_items__enriched` | 487799 | 487799 | 14 | differs | 3 | 37.37 | 7.63 |
| intermediate | `int_order_items__enriched` | 180778 | 180778 | 22 | differs | 5 | 61.23 | 11.12 |
| intermediate | `int_orders__daily` | 2779 | 2779 | 8 | differs | 6 | 40.53 | 1.48 |
| intermediate | `int_orders__item_rollup` | 124650 | 124650 | 11 | differs | 6 | 31.38 | 5.52 |
| intermediate | `int_products__returns` | 29120 | 29120 | 4 | match | 0 | 23.29 | 1.6 |
| intermediate | `int_products__sales` | 29120 | 29120 | 8 | differs | 6 | 24.33 | 2.54 |
| intermediate | `int_users__first_order_cohort` | 100000 | 100000 | 4 | match | 0 | 19.99 | 1.69 |
| intermediate | `int_users__lifetime_orders` | 100000 | 100000 | 9 | differs | 6 | 25.53 | 5.84 |
| staging | `stg_thelook__distribution_centers` | 10 | 10 | 4 | match | 0 | 19.39 | 1.53 |
| staging | `stg_thelook__events` | 2421086 | 2421086 | 13 | match | 0 | 126.46 | 8.61 |
| staging | `stg_thelook__inventory_items` | 487799 | 487799 | 12 | differs | 3 | 139.5 | 6.78 |
| staging | `stg_thelook__order_items` | 180778 | 180778 | 11 | differs | 1 | 27.47 | 4.51 |
| staging | `stg_thelook__orders` | 124650 | 124650 | 9 | match | 0 | 19.72 | 2.24 |
| staging | `stg_thelook__products` | 29120 | 29120 | 9 | differs | 3 | 16.75 | 2.04 |
| staging | `stg_thelook__users` | 100000 | 100000 | 15 | match | 0 | 14.3 | 3.99 |

## Differences, in full

### `dim_distribution_centers` (marts) - differs

| check | column | kind | spark | bigquery | detail |
|---|---|---|---|---|---|
| column_checksum | open_inventory_value | decimal | `19204625838` | `20114613026` | same input rows, different values |

### `dim_products` (marts) - differs

| check | column | kind | spark | bigquery | detail |
|---|---|---|---|---|---|
| column_checksum | unit_cost | decimal | `61429156578190` | `62840061372025` | same input rows, different values |
| column_distinct_count | unit_cost | decimal | `7435` | `26375` | same input rows, different values |
| column_checksum | retail_price | decimal | `61217180993459` | `60862284818697` | same input rows, different values |
| column_checksum | gross_revenue | decimal | `62414555291959` | `62216058072111` | same input rows, different values |
| column_distinct_count | gross_revenue | decimal | `8150` | `8918` | same input rows, different values |
| column_checksum | gross_margin | decimal | `62325735331317` | `62360717127202` | same input rows, different values |
| column_distinct_count | gross_margin | decimal | `15605` | `28562` | same input rows, different values |

### `dim_users` (marts) - differs

| check | column | kind | spark | bigquery | detail |
|---|---|---|---|---|---|
| column_checksum | lifetime_gross_revenue | decimal | `239346294806949` | `239588725613935` | same input rows, different values |
| column_distinct_count | lifetime_gross_revenue | decimal | `22892` | `32629` | same input rows, different values |
| column_checksum | lifetime_gross_margin | decimal | `239802958519185` | `241968538884933` | same input rows, different values |
| column_distinct_count | lifetime_gross_margin | decimal | `20475` | `63905` | same input rows, different values |

### `fct_inventory_items` (marts) - differs

| check | column | kind | spark | bigquery | detail |
|---|---|---|---|---|---|
| column_checksum | unit_cost | decimal | `1028825165334992` | `1053281228750666` | same input rows, different values |
| column_distinct_count | unit_cost | decimal | `7428` | `26321` | same input rows, different values |
| column_checksum | product_retail_price | decimal | `1023698061614404` | `1017432002275298` | same input rows, different values |

### `fct_order_items` (marts) - differs

| check | column | kind | spark | bigquery | detail |
|---|---|---|---|---|---|
| column_checksum | sale_price | decimal | `379699405713779` | `377194082111706` | same input rows, different values |
| column_checksum | product_cost | decimal | `381372365012265` | `390374855844143` | same input rows, different values |
| column_distinct_count | product_cost | decimal | `7428` | `26321` | same input rows, different values |
| column_checksum | gross_margin | decimal | `382320809910586` | `392186242422228` | same input rows, different values |
| column_distinct_count | gross_margin | decimal | `7792` | `26326` | same input rows, different values |
| column_checksum | product_retail_price | decimal | `379699405713779` | `377194082111706` | same input rows, different values |

### `fct_orders` (marts) - differs

| check | column | kind | spark | bigquery | detail |
|---|---|---|---|---|---|
| column_checksum | gross_revenue | decimal | `263725864593851` | `262515516797347` | same input rows, different values |
| column_distinct_count | gross_revenue | decimal | `17204` | `24441` | same input rows, different values |
| column_checksum | total_cost | decimal | `264314324502020` | `268490598399038` | same input rows, different values |
| column_distinct_count | total_cost | decimal | `15422` | `62586` | same input rows, different values |
| column_checksum | gross_margin | decimal | `264171952735456` | `269618111377568` | same input rows, different values |
| column_distinct_count | gross_margin | decimal | `16429` | `62591` | same input rows, different values |

### `int_cohorts__user_months` (intermediate) - differs

| check | column | kind | spark | bigquery | detail |
|---|---|---|---|---|---|
| column_checksum | revenue | decimal | `255336171372699` | `254360150196374` | same input rows, different values |
| column_distinct_count | revenue | decimal | `17789` | `25352` | same input rows, different values |

### `int_inventory__by_product_center` (intermediate) - differs

| check | column | kind | spark | bigquery | detail |
|---|---|---|---|---|---|
| column_checksum | open_inventory_value | decimal | `62067412308075` | `62606124036827` | same input rows, different values |
| column_distinct_count | open_inventory_value | decimal | `17978` | `28779` | same input rows, different values |
| column_checksum | open_retail_value | decimal | `62689102035682` | `62085971417297` | same input rows, different values |
| column_distinct_count | open_retail_value | decimal | `9877` | `10670` | same input rows, different values |

### `int_inventory_items__enriched` (intermediate) - differs

| check | column | kind | spark | bigquery | detail |
|---|---|---|---|---|---|
| column_checksum | unit_cost | decimal | `1028825165334992` | `1053281228750666` | same input rows, different values |
| column_distinct_count | unit_cost | decimal | `7428` | `26321` | same input rows, different values |
| column_checksum | product_retail_price | decimal | `1023698061614404` | `1017432002275298` | same input rows, different values |

### `int_order_items__enriched` (intermediate) - differs

| check | column | kind | spark | bigquery | detail |
|---|---|---|---|---|---|
| column_checksum | sale_price | decimal | `379699405713779` | `377194082111706` | same input rows, different values |
| column_checksum | product_cost | decimal | `381372365012265` | `390374855844143` | same input rows, different values |
| column_distinct_count | product_cost | decimal | `7428` | `26321` | same input rows, different values |
| column_checksum | gross_margin | decimal | `382320809910586` | `392186242422228` | same input rows, different values |
| column_distinct_count | gross_margin | decimal | `7792` | `26326` | same input rows, different values |

### `int_orders__daily` (intermediate) - differs

| check | column | kind | spark | bigquery | detail |
|---|---|---|---|---|---|
| column_checksum | gross_revenue | decimal | `5878237686768` | `5900969663808` | same input rows, different values |
| column_distinct_count | gross_revenue | decimal | `2765` | `2773` | same input rows, different values |
| column_checksum | total_cost | decimal | `5975687207838` | `5990807264489` | same input rows, different values |
| column_distinct_count | total_cost | decimal | `2766` | `2779` | same input rows, different values |
| column_checksum | gross_margin | decimal | `5920860082937` | `6034553477364` | same input rows, different values |
| column_distinct_count | gross_margin | decimal | `2762` | `2779` | same input rows, different values |

### `int_orders__item_rollup` (intermediate) - differs

| check | column | kind | spark | bigquery | detail |
|---|---|---|---|---|---|
| column_checksum | gross_revenue | decimal | `263725864593851` | `262515516797347` | same input rows, different values |
| column_distinct_count | gross_revenue | decimal | `17204` | `24441` | same input rows, different values |
| column_checksum | total_cost | decimal | `264314324502020` | `268490598399038` | same input rows, different values |
| column_distinct_count | total_cost | decimal | `15422` | `62586` | same input rows, different values |
| column_checksum | gross_margin | decimal | `264171952735456` | `269618111377568` | same input rows, different values |
| column_distinct_count | gross_margin | decimal | `16429` | `62591` | same input rows, different values |

### `int_products__sales` (intermediate) - differs

| check | column | kind | spark | bigquery | detail |
|---|---|---|---|---|---|
| column_checksum | gross_revenue | decimal | `62414555291959` | `62216058072111` | same input rows, different values |
| column_distinct_count | gross_revenue | decimal | `8150` | `8918` | same input rows, different values |
| column_checksum | total_cost | decimal | `62142277199483` | `62503798419085` | same input rows, different values |
| column_distinct_count | total_cost | decimal | `15229` | `28560` | same input rows, different values |
| column_checksum | gross_margin | decimal | `62325735331317` | `62360717127202` | same input rows, different values |
| column_distinct_count | gross_margin | decimal | `15605` | `28562` | same input rows, different values |

### `int_users__lifetime_orders` (intermediate) - differs

| check | column | kind | spark | bigquery | detail |
|---|---|---|---|---|---|
| column_checksum | lifetime_gross_revenue | decimal | `239346294806949` | `239588725613935` | same input rows, different values |
| column_distinct_count | lifetime_gross_revenue | decimal | `22892` | `32629` | same input rows, different values |
| column_checksum | lifetime_total_cost | decimal | `239934592540409` | `241898404039659` | same input rows, different values |
| column_distinct_count | lifetime_total_cost | decimal | `19359` | `63905` | same input rows, different values |
| column_checksum | lifetime_gross_margin | decimal | `239802958519185` | `241968538884933` | same input rows, different values |
| column_distinct_count | lifetime_gross_margin | decimal | `20475` | `63905` | same input rows, different values |

### `mart_cohort_retention` (marts) - differs

| check | column | kind | spark | bigquery | detail |
|---|---|---|---|---|---|
| column_checksum | revenue | decimal | `8312419761548` | `8373291297589` | same input rows, different values |
| column_distinct_count | revenue | decimal | `3734` | `3790` | same input rows, different values |

### `mart_customer_summary` (marts) - differs

| check | column | kind | spark | bigquery | detail |
|---|---|---|---|---|---|
| column_checksum | lifetime_gross_revenue | decimal | `239346294806949` | `239588725613935` | same input rows, different values |
| column_distinct_count | lifetime_gross_revenue | decimal | `22892` | `32629` | same input rows, different values |
| column_checksum | lifetime_gross_margin | decimal | `239802958519185` | `241968538884933` | same input rows, different values |
| column_distinct_count | lifetime_gross_margin | decimal | `20475` | `63905` | same input rows, different values |
| column_checksum | average_order_value | decimal | `169588895276672` | `169997929119394` | same input rows, different values |
| column_distinct_count | average_order_value | decimal | `17659` | `17688` | same input rows, different values |

### `mart_daily_revenue` (marts) - differs

| check | column | kind | spark | bigquery | detail |
|---|---|---|---|---|---|
| column_checksum | gross_revenue | decimal | `5878237686768` | `5900969663808` | same input rows, different values |
| column_distinct_count | gross_revenue | decimal | `2765` | `2773` | same input rows, different values |
| column_checksum | total_cost | decimal | `5975687207838` | `5990807264489` | same input rows, different values |
| column_distinct_count | total_cost | decimal | `2766` | `2779` | same input rows, different values |
| column_checksum | gross_margin | decimal | `5920860082937` | `6034553477364` | same input rows, different values |
| column_distinct_count | gross_margin | decimal | `2762` | `2779` | same input rows, different values |
| column_checksum | average_order_value | decimal | `5928012599461` | `5909314317784` | same input rows, different values |
| column_distinct_count | average_order_value | decimal | `2271` | `2273` | same input rows, different values |

### `mart_product_performance` (marts) - differs

| check | column | kind | spark | bigquery | detail |
|---|---|---|---|---|---|
| column_checksum | unit_cost | decimal | `61429156578190` | `62840061372025` | same input rows, different values |
| column_distinct_count | unit_cost | decimal | `7435` | `26375` | same input rows, different values |
| column_checksum | retail_price | decimal | `61217180993459` | `60862284818697` | same input rows, different values |
| column_checksum | gross_revenue | decimal | `62414555291959` | `62216058072111` | same input rows, different values |
| column_distinct_count | gross_revenue | decimal | `8150` | `8918` | same input rows, different values |
| column_checksum | total_cost | decimal | `62142277199483` | `62503798419085` | same input rows, different values |
| column_distinct_count | total_cost | decimal | `15229` | `28560` | same input rows, different values |
| column_checksum | gross_margin | decimal | `62325735331317` | `62360717127202` | same input rows, different values |
| column_distinct_count | gross_margin | decimal | `15605` | `28562` | same input rows, different values |
| column_checksum | gross_margin_rate | float64 | `62295364512690` | `61560196244972` | same input rows, different values |
| column_distinct_count | gross_margin_rate | float64 | `18696` | `328` | same input rows, different values |

### `stg_thelook__inventory_items` (staging) - differs

| check | column | kind | spark | bigquery | detail |
|---|---|---|---|---|---|
| column_checksum | cost | decimal | `1028825165334992` | `1053281228750666` | same input rows, different values |
| column_distinct_count | cost | decimal | `7428` | `26321` | same input rows, different values |
| column_checksum | product_retail_price | decimal | `1023698061614404` | `1017432002275298` | same input rows, different values |

### `stg_thelook__order_items` (staging) - differs

| check | column | kind | spark | bigquery | detail |
|---|---|---|---|---|---|
| column_checksum | sale_price | decimal | `379699405713779` | `377194082111706` | same input rows, different values |

### `stg_thelook__products` (staging) - differs

| check | column | kind | spark | bigquery | detail |
|---|---|---|---|---|---|
| column_checksum | cost | decimal | `61429156578190` | `62840061372025` | same input rows, different values |
| column_distinct_count | cost | decimal | `7435` | `26375` | same input rows, different values |
| column_checksum | retail_price | decimal | `61217180993459` | `60862284818697` | same input rows, different values |

## TRAPS, each with its decision

1. **BIGNUMERIC cannot exist on Spark.** Spark DECIMAL caps at precision 38
   (measured); `decimal_type(p > 38)` raises on Spark by design instead of
   rendering `double`. A `bignumeric` canonical type would be named here, never
   widened away.
2. **DECIMAL(18,2) vs NUMERIC.** Types compare by *kind* (decimal == numeric),
   never precision; both raw types are recorded. Values compare exactly after
   dropping trailing fractional zeros (Spark prints the declared scale, BigQuery
   the shortest form) - which is where the money prediction is decided.
3. **Floating point** compares as integer micro-units
   (`CAST(ROUND(x * 1000000) AS BIGINT/INT64)`), not as text, no tolerance.
4. **TIMESTAMP vs TIMESTAMP_NTZ**: instants compare as microseconds since the
   epoch (Spark `unix_micros`, BigQuery `UNIX_MICROS`); `timestamp_ntz`
   (BigQuery DATETIME) is its own kind, so instant-vs-wall-clock gates. The Spark
   session must be UTC (checked by the self-check).
5. **Arrays and structs** compare structurally: arrays sorted and joined with
   `|`, structs field by field, recursively. A NULL array or struct renders as
   NULL on both engines, so it is never conflated with an empty one. The Spark
   adapter cannot fetch an ARRAY column at all; nothing here returns one - only
   aggregates leave the engine.
6. **Row order and NULLS ordering**: every metric is an aggregate; the only sort
   is of an array's own values, the same on both engines.
7. **NULLs**: explicit null and distinct counts per column, so an all-NULL column
   cannot masquerade as all-zero.
8. **The live dataset**: BigQuery reads the public dataset now, Spark a snapshot;
   the sources are compared first and drift is reported as drift.

## Reproduce

```bash
make load-sources                          # the Spark snapshot of the real rows
python3 scripts/parity.py                  # --same-data is the default
python3 scripts/parity.py --self-check     # only the digest portability step
```

Both legs are read-only: each model is the ephemeral compile of the DAG, run as
one query. BigQuery needs `BQ_KEYFILE` (default
`~/.config/gcp/coreychimpbot-sa.json`) and `openssl`; queries are capped at
`BQ_MAXIMUM_BYTES_BILLED` (1 GB) each. Spark needs the Thrift Server
(`scripts/start_spark.sh`) and the loaded sources (`make load-sources`).
