"""Download the REAL thelook_ecommerce tables from BigQuery to Parquet, for Spark to land.

The counterpart of scripts/render_fixture.py: same seven tables, same output shape, but
the rows are bigquery-public-data.thelook_ecommerce itself, so the Trino leg builds on
exactly the rows the BigQuery leg reads. Each table is written to
target/stack_io/real/<table>.parquet, which the Spark container sees as /data/real
(`SOURCE_DIR=/data/real` for land_sources.py; `make land-real` does both).

Rows are read with tabledata.list (the REST API), which is free: no query runs and no
bytes are billed. GEOGRAPHY arrives as WKT text, which is what the fixture path writes
too (geography_type() is varchar on Trino). TIMESTAMP arrives as a UTC instant.

Credentials: BQ_KEYFILE (a service-account key) or Application Default Credentials.
BQ_PROJECT names the project the API calls are attributed to.

    uv run python scripts/render_real.py           # or: make real-sources
"""
from __future__ import annotations

import os
import pathlib
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pyarrow.parquet as pq
from google.cloud import bigquery

HERE = pathlib.Path(__file__).resolve().parent.parent
OUT = HERE / "target" / "stack_io" / "real"
SOURCE = "bigquery-public-data.thelook_ecommerce"
TABLES = ["distribution_centers", "products", "users", "inventory_items", "orders", "order_items", "events"]


def client() -> bigquery.Client:
    project = os.environ.get("BQ_PROJECT")
    keyfile = os.environ.get("BQ_KEYFILE")
    if keyfile:
        return bigquery.Client.from_service_account_json(keyfile, project=project)
    return bigquery.Client(project=project)


def download(bq: bigquery.Client, table: str) -> tuple[str, int, int, float]:
    start = time.monotonic()
    ref = bq.get_table(f"{SOURCE}.{table}")
    arrow = bq.list_rows(ref, page_size=50_000).to_arrow(create_bqstorage_client=False)
    if arrow.num_rows != ref.num_rows:
        raise RuntimeError(f"{table}: read {arrow.num_rows} rows, the table holds {ref.num_rows}")
    pq.write_table(arrow, OUT / f"{table}.parquet")
    return table, arrow.num_rows, arrow.num_columns, time.monotonic() - start


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    bq = client()
    print(f"downloading {SOURCE} (tabledata.list, no query, nothing billed) -> {OUT.relative_to(HERE)}")
    with ThreadPoolExecutor(max_workers=len(TABLES)) as pool:
        for table, rows, cols, secs in pool.map(lambda t: download(bq, t), TABLES):
            print(f"  {table:<22} {rows:>9} rows  {cols} columns  {secs:6.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
