# Value parity: BigQuery vs Trino on the same real rows

*Measured 2026-10-07: dbt-core 1.11.11, dbt-bigquery 1.11.0, dbt-trino 1.10.2, Trino 483,
Spark 4.0.1, Iceberg 1.10.0. Both legs read the same snapshot of
`bigquery-public-data.thelook_ecommerce` (3,347,594 rows in 7 tables).*

## Result

**30 of 30 relations are identical on BigQuery and Trino: 887 of 887 profile metrics
equal, 0 row-count differences, 0 column-name differences.** That includes every money
column. `money_type()` is `NUMERIC` on BigQuery and `decimal(38,9)` on Trino, and their
sums agree to the ninth decimal place, for example
`mart_product_performance.gross_revenue` = `10808138.471315387` on both. The two
`average_order_value` metrics also agree (`mart_customer_summary`: `6914547.45` on both).
Those metrics are `round(x / nullif(y, 0), 2)`, which project 1 predicted could differ
under Trino's decimal division rules. They do not.

Project 1 could not reach this result with DuckDB at the time: 21 of 29 models differed
on money because `decimal(18,2)` rounded what BigQuery's `NUMERIC` keeps. It has since
moved to `decimal(38,9)` and exact division (`money_quotient()`), and its DuckDB leg is
equal to BigQuery in every cell too
([`../../1_dbt_bigquery_duckdb/analyses/money_fix/README.md`](../../1_dbt_bigquery_duckdb/analyses/money_fix/README.md)).
Both models now compute `average_order_value` as `round(money_quotient(x, y), 2)`; on
Trino that renders the same `x / nullif(y, 0)` measured here.

The row-by-row comparison, and the representation differences it names, are in
[`row_parity.md`](row_parity.md): 30 / 30 relations equal row for row.

## How it was run

```bash
export BQ_KEYFILE=/path/to/key.json BQ_PROJECT=<gcp project>   # the profile then uses method: service-account
make bq            # dbt build --target bigquery: 197 pass, 1 warn, 0 error (152 s)
make stack-up
make trino-real    # real-sources (download, no query billed) + Spark lands them + dbt build --target trino
                   #   197 pass, 1 warn, 0 error (47 s)
make parity        # scripts/bq_trino_parity.py -> target/parity/report.{md,json}
make interop       # Spark on the real-data marts: 12/12 tables identical to Trino
```

The one warning on each leg is the deliberate `severity: warn` test
`assert_order_item_created_at_is_plausible`, which flags dirty timestamps in the public
dataset. It returned **137,807 rows on both engines**.

`scripts/bq_trino_parity.py` computes the same per-column profile on both engines:
non-null count; exact sum for integers and decimals; sum to 1e-9 relative for doubles;
distinct count and total length for text; distinct count and min/max for dates;
distinct count and min/max epoch microseconds for timestamps; total cardinality for
arrays. On BigQuery, `GEOGRAPHY` is profiled as `ST_ASTEXT` and `JSON` as
`TO_JSON_STRING`, the text Trino stores. A first run with Trino on the fixture and
BigQuery on real data reported 28 of 30 relations different, which shows the harness
does detect differences.

## Real data on the Trino leg

`scripts/render_real.py` downloads the seven tables with `tabledata.list` (no query, so
nothing is billed; ~6 min, dominated by the 2.4M-row `events`). Spark then lands them in
`lake.thelook_ecommerce`, the same path the fixture takes (`SOURCE_DIR=/data/real`).
This was chosen over Trino's BigQuery connector ([`architecture.md`](architecture.md) §4)
because it keeps Spark as the producer of raw data and needs no credential inside the
Trino container.

Note: the public dataset is a live demo dataset and can change between reads. Run `make bq` and `make real-sources`
close together, or the two legs can read different snapshots. The row counts in the
report would show it.

## The report

| relation | type | status | rows (Trino / BQ) | differing metrics |
|---|---|---|---:|---|
| `dim_date` | table | identical | 2824 / 2824 | 0/24 |
| `dim_distribution_centers` | table | identical | 10 / 10 | 0/18 |
| `dim_products` | table | identical | 29120 / 29120 | 0/37 |
| `dim_users` | table | identical | 100000 / 100000 | 0/58 |
| `fct_inventory_items` | table | identical | 488895 / 488895 | 0/32 |
| `fct_order_items` | table | identical | 181070 / 181070 | 0/55 |
| `fct_orders` | table | identical | 124885 / 124885 | 0/41 |
| `int_cohorts__user_months` | view | identical | 120712 / 120712 | 0/20 |
| `int_events__sessions` | view | identical | 681070 / 681070 | 0/28 |
| `int_inventory__by_product_center` | view | identical | 29056 / 29056 | 0/18 |
| `int_inventory_items__enriched` | view | identical | 488895 / 488895 | 0/38 |
| `int_order_items__enriched` | view | identical | 181070 / 181070 | 0/63 |
| `int_orders__daily` | view | identical | 2775 / 2775 | 0/19 |
| `int_orders__item_rollup` | view | identical | 124885 / 124885 | 0/28 |
| `int_products__returns` | view | identical | 29120 / 29120 | 0/9 |
| `int_products__sales` | view | identical | 29120 / 29120 | 0/21 |
| `int_users__first_order_cohort` | view | identical | 100000 / 100000 | 0/15 |
| `int_users__lifetime_orders` | view | identical | 100000 / 100000 | 0/23 |
| `mart_cohort_retention` | table | identical | 3887 / 3887 | 0/22 |
| `mart_customer_summary` | table | identical | 100000 / 100000 | 0/35 |
| `mart_daily_revenue` | table | identical | 2775 / 2775 | 0/21 |
| `mart_polyglot_types` | table | identical | 1 / 1 | 0/11 |
| `mart_product_performance` | table | identical | 29120 / 29120 | 0/41 |
| `stg_thelook__distribution_centers` | view | identical | 10 / 10 | 0/10 |
| `stg_thelook__events` | view | identical | 2423614 / 2423614 | 0/38 |
| `stg_thelook__inventory_items` | view | identical | 488895 / 488895 | 0/34 |
| `stg_thelook__order_items` | view | identical | 181070 / 181070 | 0/32 |
| `stg_thelook__orders` | view | identical | 124885 / 124885 | 0/29 |
| `stg_thelook__products` | view | identical | 29120 / 29120 | 0/24 |
| `stg_thelook__users` | view | identical | 100000 / 100000 | 0/43 |

Summary: 30 / 30 relations identical; profiling billed 0.0 MB on BigQuery.
