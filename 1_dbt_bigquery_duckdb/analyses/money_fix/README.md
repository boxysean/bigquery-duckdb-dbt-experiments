# The money fix: DuckDB equal to BigQuery on every value

*Measured 2026-10-07 on DuckDB 1.5.5 and dbt-oss 2.0.5, over the same snapshot of
`bigquery-public-data.thelook_ecommerce` (3,347,594 rows) that project 2's BigQuery and
Trino legs were compared on.*

## Result

With two changes, this project's DuckDB leg returns the same value as BigQuery in every
cell: **30 of 30 relations equal row for row, 0 of 79,839,931 cells different**, 0 rows on
one side only.

| DuckDB leg | Relations equal | Cells different |
|---|---:|---:|
| Before: `money_type()` = `decimal(18,2)` | 9 / 30 | 5,006,179 (55 columns: 54 money, 1 rate derived from money) |
| `money_type()` = `decimal(38,9)` only | 29 / 30 | 1 (`mart_customer_summary.average_order_value`, user 40081: BigQuery `141.13`, DuckDB `141.12`) |
| **`decimal(38,9)` and `money_quotient()`** (this change) | **30 / 30** | **0** |

All three built `198 total | 197 success | 1 warn`; the warning is the deliberate dirty-data
test `assert_order_item_created_at_is_plausible`. The 9,119,763 cells counted
`equivalent` on every leg are timestamps: equal instants, with a naive DuckDB timestamp
against BigQuery's `TIMESTAMP`, the same representation difference project 2 documents for
Trino.

## The two changes

1. **`money_type()` is `decimal(38,9)` on DuckDB**, exactly BigQuery's `NUMERIC`
   (`macros/polyglot/types.sql`). `decimal(18,2)` rounded the source's sub-cent `FLOAT64`
   prices and costs to cents on DuckDB only, the cause of the differences above
   ([`docs/gaps.md`](../../docs/gaps.md)).
2. **`money_quotient(n, d)`** (`macros/polyglot/math.sql`), used by the two
   `average_order_value` columns as `round(money_quotient(x, y), 2)`. BigQuery's
   `NUMERIC / INT64` is `NUMERIC`, the quotient rounded to nine decimals half away from
   zero. DuckDB divides every `DECIMAL` in `DOUBLE`, which cannot hold a half-way quotient
   such as `191.249999999 / 2 = 95.6249999995` exactly, so rounding to cents can land on
   the other side ([`docs/challenges.md`](../../docs/challenges.md) 10.4). The DuckDB branch
   divides in integers (the numerator in nanos as a `HUGEINT`); the BigQuery branch renders
   `x / nullif(y, 0)`, the SQL the models had before.

How the division was checked, before the build:

- The integer method against Python's exact decimal arithmetic (half away from zero, nine
  decimals): **20,008 of 20,008** equal, including negatives and values near 10^11.
- BigQuery's own rule, on BigQuery: `NUMERIC / INT64` for **3,005 of 3,005** cases equals
  that same arithmetic.
- The shortcut `cast(x / n as decimal(38,9))` (round the DOUBLE back to nine decimals) is
  **not** a fix: it was wrong on 102 of 5,000 random half-way cases.

The self-check (`make polyglot`) carries the half-way case and four more
(`money_quotient …`), 52 cases in all.

## How it was measured

Three copies of this project, identical except for the changes above, were built over the
real rows, loaded into `dev.duckdb` from the Parquet files project 2's
`scripts/render_real.py` downloads (`TIMESTAMP` as `TIMESTAMPTZ`, `GEOGRAPHY` as
`GEOMETRY`, as `scripts/load_duckdb_real_sources.sh` maps them). `compare_duckdb.py`
(next to this file) then compared each with project 2's BigQuery build of the same SQL,
row by row; the reports are in `results/`.

Why not `make value-parity`: it reads the real rows with the community `bigquery`
extension through the BigQuery Storage API and builds the BigQuery leg in
`coreychimpbot`, and the session that measured this had a key for neither (its service
account lacks `bigquery.readsessions.create`). Its network also blocked DuckDB's extension
repositories and the `dbc` driver index, so the builds ran with the official DuckDB 1.5.5
`libduckdb` from GitHub as the ADBC driver and with `extensions: []` in a scratch
`profiles.yml`. The sources were local tables, so no extension was needed. The models,
macros and DuckDB version were the ones in this repository.

Cost: 2.46 GB billed by BigQuery per comparison (three runs).
