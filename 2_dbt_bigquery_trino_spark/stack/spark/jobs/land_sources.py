"""Spark, the UPSTREAM producer: land the raw thelook_ecommerce tables in the lakehouse.

In the architecture this project models, raw data is produced by Spark pipelines and
transformed by dbt on Trino. This job plays that Spark pipeline: it reads the seven
Parquet files scripts/render_fixture.py wrote (project 1's fixture, the same rows
project 1's DuckDB leg reads) and writes them as Iceberg tables
lake.thelook_ecommerce.<table> through the shared REST catalog. dbt then reads them on
Trino as source('thelook_ecommerce', <table>): Trino never asks Spark for anything, it
reads the tables Spark committed.

Gates (exit 1 on any): every table lands, its row count equals the Parquet file's, and
every timestamp column is a Spark TIMESTAMP (an instant: Iceberg timestamptz, Trino
timestamp(6) with time zone), never TIMESTAMP_NTZ.

    docker compose run --rm spark land_sources.py      # or: make land-sources
"""
import sys

from pyspark.sql import SparkSession
from pyspark.sql.types import TimestampNTZType, TimestampType

TABLES = ["distribution_centers", "products", "users", "inventory_items", "orders", "order_items", "events"]

spark = SparkSession.builder.appName("land_sources").getOrCreate()
spark.sparkContext.setLogLevel("ERROR")
spark.sql("create namespace if not exists lake.thelook_ecommerce")

failures = []
for table in TABLES:
    df = spark.read.parquet(f"/data/fixture/{table}.parquet")
    expected = df.count()
    ntz = [f.name for f in df.schema.fields if isinstance(f.dataType, TimestampNTZType)]
    if ntz:
        failures.append(f"{table}: naive timestamp columns {ntz} (instants expected)")
    df.writeTo(f"lake.thelook_ecommerce.{table}").using("iceberg").createOrReplace()
    landed = spark.table(f"lake.thelook_ecommerce.{table}").count()
    ts = [f.name for f in df.schema.fields if isinstance(f.dataType, TimestampType)]
    status = "ok" if landed == expected else "FAIL"
    if landed != expected:
        failures.append(f"{table}: landed {landed} rows, the file holds {expected}")
    print(f"  {status:<4} lake.thelook_ecommerce.{table:<22} {landed:>6} rows  timestamptz: {', '.join(ts) or '-'}")

if failures:
    print("\nland_sources: FAILED")
    for f in failures:
        print(f"  {f}")
    sys.exit(1)
print(f"\nland_sources: {len(TABLES)} tables landed by Spark {spark.version} in lake.thelook_ecommerce")
