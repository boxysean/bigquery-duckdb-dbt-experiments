# Row-level parity: BigQuery vs Trino, row by row

*Measured 2026-10-07 on the same real rows as [`value_parity.md`](value_parity.md)
(`make bq`, `make trino-real`, then `make rows`).*

## Result

**30 of 30 relations are equal row for row.** 6,296,884 rows matched on their
`unique`-tested key, with **0 rows on one engine only** and 0 duplicate keys. Of the
79,839,931 cells compared, **0 are different**:

- **70,720,168 are identical**: equal as stored, with no conversion.
- **9,119,763 are equivalent**: equal only after a stated normalisation. Every one of
  them is in two kinds of column. 9,119,762 cells are in the 49 `timestamp(6)` columns and
  1 is in the `JSON` column (`mart_polyglot_types.pair_json`).

Doubles are **bit-identical** in all 14 `double` / `FLOAT64` columns, so the 1e-12
relative tolerance the script allows was never needed. Money (`decimal(38,9)` /
`NUMERIC`, 54 columns) is exactly equal in every cell.

## The representation differences, and what they mean

The values agree, but the two engines do not type or render them the same way. These
are the places where a consumer could see a difference that is not one: a text export, a
string comparison, a reader with a different time zone.

| Trino type | BigQuery type | Columns | Values | Text each engine renders (BigQuery / Trino) | What it means |
|---|---|---:|---|---|---|
| `timestamp(6)` | `TIMESTAMP` | 49 | equal **as UTC** | `2019-01-01 00:00:00+00` / `2019-01-01 00:00:00.000000` | BigQuery stores an **instant**; Trino stores a **naive** wall-clock time that is UTC only by the project's convention (`to_utc_timestamp`, [`challenges.md`](challenges.md) 4.3). Equal in every cell under that convention. A reader that takes Trino's value in another time zone gets a different instant |
| `decimal(38,9)` | `NUMERIC` | 54 | identical | `563928.92198433` / `563928.921984330`, `345` / `345.000000000` | Same value and scale. Trino pads text to 9 decimals; BigQuery trims trailing zeros. 3,397 of 10,610 sampled cells render differently |
| `double` | `FLOAT64` | 14 | identical (bit for bit) | `34.05` / `3.405E1` | Trino casts a double to text in scientific notation. 1,786 of 2,040 sampled cells render differently |
| `varchar` | `JSON` | 1 | equal **after parsing** | `{"channel":"web","id":1}` / `{"id":1,"channel":"web"}` | Different types (Iceberg has no JSON type, so Trino stores JSON text). The key order differs, so a string comparison fails and a parsed comparison passes |
| `bigint` / `boolean` / `date` / `varchar` | `INT64` / `BOOL` / `DATE` / `STRING` | 208 | identical | the same text | No difference |
| `array(bigint)`, `array(date)`, `row(...)` | `ARRAY<INT64>`, `ARRAY<DATE>`, `STRUCT<...>` | 3 | identical | the same JSON | Elements, field names and field order agree |

The text rendering was sampled on up to 200 keys per relation.

## How the comparison works (`scripts/bq_trino_rows.py`)

1. **Move Trino's rows to where BigQuery's are.** Each Trino relation is read through the
   Trino client into Parquet, with the types mapped one to one: `decimal(38,9)` →
   `decimal128(38,9)`, `timestamp(6)` → naive microsecond timestamp, `row` → struct,
   `array` → list. A BigQuery **load job**, which is free, then loads the file as
   `<project>.trino_experiments_<env>_trino_rows.<relation>`. The loaded row count must
   equal Trino's (the transfer gate). The rows go this way because the service account
   cannot use the BigQuery Storage Read API (`bigquery.readsessions.create`), and pulling
   6.3M rows through the REST API is slow.
2. **Join on the key.** In BigQuery SQL, a FULL OUTER JOIN on the model's `unique`-tested
   column (from `target/manifest.json`). `mart_polyglot_types` has one row and no key.
   Rows present on one side only, and duplicate keys, are counted.
3. **Classify every cell** as `identical`, `equivalent` (the normalisation is named per
   column) or `different`. A NULL on one side only is `different`. Up to 5 example keys
   are kept for every column that is not identical, with the differing ones first.
4. **Compare the rendered text** on a sample of keys: Trino `cast(x as varchar)` (or
   `json_format` for nested values) against BigQuery `CAST(x AS STRING)` (or
   `TO_JSON_STRING`).

**Control: it catches real differences.** Run against a Trino copy of `fct_orders` with
four planted changes (`ROWS_TRINO_SCHEMA=analytics_ctl ROWS_ONLY=fct_orders`), it reported
exactly those four and nothing else:

| Planted in the Trino copy | Reported |
|---|---|
| order 2 deleted | only on BigQuery: key `2` |
| `gross_revenue` + 0.000000001 on order 1 | different: `31.979999542` / `31.979999543` |
| `order_created_at` + 1 ms on order 3 | different: `…09:39:47Z` / `…09:39:47.001Z` |
| `order_status` lower-cased plus a trailing space on order 4 | different: `Cancelled` / `cancelled ` |

**Limits.**
- The Trino side passes through Parquet and a BigQuery load. Every mapping above is
  lossless for the types the project uses, but the transfer gate checks row counts only.
- The load reads a naive Parquet timestamp as UTC. That is the same assumption the
  `equivalent` class names for the timestamp columns.
- Cost: 2.46 GB billed by BigQuery for the full run; about 8 minutes, most of it the
  2.4M-row `stg_thelook__events`.

## The report (`target/rows/report.md`, per relation)

| relation | key | status | rows matched | rows identical | rows equal | only BQ / only Trino | dup keys BQ / Trino |
|---|---|---|---:|---:|---:|---:|---:|
| `dim_date` | `date_day` | equal | 2,824 | 0 | 2,824 | 0 / 0 | 0 / 0 |
| `dim_distribution_centers` | `distribution_center_id` | equal | 10 | 10 | 10 | 0 / 0 | 0 / 0 |
| `dim_products` | `product_id` | equal | 29,120 | 29,120 | 29,120 | 0 / 0 | 0 / 0 |
| `dim_users` | `user_id` | equal | 100,000 | 0 | 100,000 | 0 / 0 | 0 / 0 |
| `fct_inventory_items` | `inventory_item_id` | equal | 488,895 | 0 | 488,895 | 0 / 0 | 0 / 0 |
| `fct_order_items` | `inventory_item_id` | equal | 181,070 | 0 | 181,070 | 0 / 0 | 0 / 0 |
| `fct_orders` | `order_id` | equal | 124,885 | 0 | 124,885 | 0 / 0 | 0 / 0 |
| `int_cohorts__user_months` | `user_month_key` | equal | 120,712 | 0 | 120,712 | 0 / 0 | 0 / 0 |
| `int_events__sessions` | `session_id` | equal | 681,070 | 0 | 681,070 | 0 / 0 | 0 / 0 |
| `int_inventory__by_product_center` | `product_center_key` | equal | 29,056 | 29,056 | 29,056 | 0 / 0 | 0 / 0 |
| `int_inventory_items__enriched` | `inventory_item_id` | equal | 488,895 | 0 | 488,895 | 0 / 0 | 0 / 0 |
| `int_order_items__enriched` | `inventory_item_id` | equal | 181,070 | 0 | 181,070 | 0 / 0 | 0 / 0 |
| `int_orders__daily` | `order_date` | equal | 2,775 | 2,775 | 2,775 | 0 / 0 | 0 / 0 |
| `int_orders__item_rollup` | `order_id` | equal | 124,885 | 0 | 124,885 | 0 / 0 | 0 / 0 |
| `int_products__returns` | `product_id` | equal | 29,120 | 29,120 | 29,120 | 0 / 0 | 0 / 0 |
| `int_products__sales` | `product_id` | equal | 29,120 | 64 | 29,120 | 0 / 0 | 0 / 0 |
| `int_users__first_order_cohort` | `user_id` | equal | 100,000 | 0 | 100,000 | 0 / 0 | 0 / 0 |
| `int_users__lifetime_orders` | `user_id` | equal | 100,000 | 20,096 | 100,000 | 0 / 0 | 0 / 0 |
| `mart_cohort_retention` | `cohort_activity_key` | equal | 3,887 | 0 | 3,887 | 0 / 0 | 0 / 0 |
| `mart_customer_summary` | `user_id` | equal | 100,000 | 0 | 100,000 | 0 / 0 | 0 / 0 |
| `mart_daily_revenue` | `revenue_date` | equal | 2,775 | 2,775 | 2,775 | 0 / 0 | 0 / 0 |
| `mart_polyglot_types` | `(single row)` | equal | 1 | 0 | 1 | 0 / 0 | 0 / 0 |
| `mart_product_performance` | `product_id` | equal | 29,120 | 64 | 29,120 | 0 / 0 | 0 / 0 |
| `stg_thelook__distribution_centers` | `distribution_center_id` | equal | 10 | 10 | 10 | 0 / 0 | 0 / 0 |
| `stg_thelook__events` | `event_id` | equal | 2,423,614 | 0 | 2,423,614 | 0 / 0 | 0 / 0 |
| `stg_thelook__inventory_items` | `inventory_item_id` | equal | 488,895 | 0 | 488,895 | 0 / 0 | 0 / 0 |
| `stg_thelook__order_items` | `order_item_id` | equal | 181,070 | 0 | 181,070 | 0 / 0 | 0 / 0 |
| `stg_thelook__orders` | `order_id` | equal | 124,885 | 0 | 124,885 | 0 / 0 | 0 / 0 |
| `stg_thelook__products` | `product_id` | equal | 29,120 | 29,120 | 29,120 | 0 / 0 | 0 / 0 |
| `stg_thelook__users` | `user_id` | equal | 100,000 | 0 | 100,000 | 0 / 0 | 0 / 0 |

