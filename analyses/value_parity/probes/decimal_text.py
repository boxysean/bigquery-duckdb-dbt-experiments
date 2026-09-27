"""Probe: do DuckDB DECIMAL(18,2) and BigQuery NUMERIC render one value as one text?

    python3 analyses/value_parity/probes/decimal_text.py   # needs BQ_KEYFILE; reads
                                                             # dev.duckdb (real load) and
                                                             # experiments_dev

Why it exists: the first value-parity run showed columns such as
stg_thelook__order_items.sale_price with equal distinct counts on both legs but
different checksums. Two causes, separated here:

* text: `CAST(<decimal> AS text)` keeps the declared scale on DuckDB ('12.30', '12.00')
  and is shortest-form on BigQuery ('12.3', '12'); scripts/parity.py hashed that text,
  so equal cents hashed differently (fixed in Engine.canon, kind "decimal");
* value: money_type() is decimal(18,2) on DuckDB and NUMERIC (scale 9) on BigQuery
  (macros/polyglot/types.sql), so a FLOAT64 source value keeps its binary noise on
  BigQuery ('0.49000001') and is rounded to cents on DuckDB ('0.49').
"""
import importlib.util
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
spec = importlib.util.spec_from_file_location("parity", f"{REPO}/scripts/parity.py")
parity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parity)

duck = parity.DuckLeg(f"{REPO}/dev.duckdb")
bq = parity.BigQueryLeg(os.environ["BQ_KEYFILE"], "coreychimpbot")

print("constants:")
print("  duckdb  ", duck.sql("select cast(cast(12.30 as decimal(18,2)) as varchar) a,"
                           " cast(cast(12 as decimal(18,2)) as varchar) b,"
                           " cast(cast(0.5 as decimal(18,2)) as varchar) c"))
print("  bigquery", bq.query("select cast(numeric '12.30' as string) a,"
                           " cast(cast(12 as numeric) as string) b,"
                           " cast(numeric '0.5' as string) c")[1])

print("stg_thelook__order_items.sale_price, first 5 by value:")
print("  duckdb  ", duck.sql("select cast(sale_price as varchar) t from main.stg_thelook__order_items"
                           " group by 1 order by min(sale_price) limit 5"))
print("  bigquery", bq.query("select cast(sale_price as string) t from"
                           " `coreychimpbot.experiments_dev.stg_thelook__order_items`"
                           " group by 1 order by min(sale_price) limit 5")[1])
print("  duckdb rows whose text ends in 0 after the point:",
      duck.sql("select count(*) n from main.stg_thelook__order_items"
               " where cast(sale_price as varchar) like '%.%0'"))
print("  bigquery rows whose value is not a whole number of cents:",
      bq.query("select count(*) n from"
               " `coreychimpbot.experiments_dev.stg_thelook__order_items`"
               " where sale_price <> round(sale_price, 2)")[1])
print("  bigquery products.cost rows not a whole number of cents:",
      bq.query("select count(*) n, countif(cost <> round(cost, 2)) off_cents from"
               " `coreychimpbot.experiments_dev.stg_thelook__products`")[1])
# Why products.cost still differs after rounding BigQuery to cents: both paths
# emulated on DuckDB's copy of the raw FLOAT64 source. DuckDB: DOUBLE -> DECIMAL(18,2)
# in one step. BigQuery: FLOAT64 -> NUMERIC (9 decimals), which a later ROUND(x, 2)
# rounds again - a value such as 1.00499999999 becomes 1.005000000 and then 1.01.
print("raw thelook_ecommerce.products.cost (DOUBLE), cents after one vs two roundings:")
print("  duckdb  ", duck.sql(
    "select count(*) n,"
    " count(*) filter (where cast(cost as decimal(18,2))"
    "   <> round(cast(cost as decimal(38,9)), 2)) differ_at_cents,"
    " min(cost) filter (where cast(cost as decimal(18,2))"
    "   <> round(cast(cost as decimal(38,9)), 2)) example_raw"
    " from thelook_ecommerce.products"))
# mart_product_performance.gross_margin_rate: 328 distinct values on BigQuery, 18,699
# on DuckDB. The raw margin ratio takes few values; rounding cost to cents first
# scatters it.
print("distinct (1 - cost / retail_price) at 1e-6, raw DOUBLE vs cents:")
print("  duckdb  ", duck.sql(
    "select count(distinct round((1 - cost / retail_price) * 1000000)) raw_ratio_distinct,"
    " count(distinct round((1 - cast(cost as decimal(18,2))"
    "   / cast(retail_price as decimal(18,2))) * 1000000)) cents_ratio_distinct"
    " from thelook_ecommerce.products"))
sys.exit(0)
