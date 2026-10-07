"""Render the shared thelook_ecommerce fixture to Parquet, for Spark to land.

The fixture is NOT copied: this reads project 1's own file,
../1_dbt_bigquery_duckdb/scripts/fixtures/thelook_ecommerce.sql, and runs it in an
in-memory DuckDB (the same engine project 1 uses to build it), so both projects read the
very same rows. Each of the seven tables is written to
target/stack_io/fixture/<table>.parquet, which stack/compose.yml mounts into the Spark
container at /data/fixture.

One conversion, and only one: the two GEOGRAPHY columns (users.user_geom,
distribution_centers.distribution_center_geom) are DuckDB GEOMETRY in the fixture.
Neither Iceberg nor Spark has a geography type, so they are written as WKT text
(`POINT(lon lat)`), which is what geography_type() renders on Trino (varchar).
Timestamps are TIMESTAMPTZ and land as Parquet instants (isAdjustedToUTC=true), which
Spark reads as TIMESTAMP and Iceberg stores as timestamptz: no instant moves.

    uv run python scripts/render_fixture.py        # or: make fixture
"""
from __future__ import annotations

import pathlib
import sys

import duckdb

HERE = pathlib.Path(__file__).resolve().parent.parent
FIXTURE_SQL = HERE.parent / "1_dbt_bigquery_duckdb" / "scripts" / "fixtures" / "thelook_ecommerce.sql"
OUT = HERE / "target" / "stack_io" / "fixture"
TABLES = ["distribution_centers", "products", "users", "inventory_items", "orders", "order_items", "events"]


def main() -> int:
    if not FIXTURE_SQL.is_file():
        print(f"FAIL  project 1's fixture is missing: {FIXTURE_SQL}", file=sys.stderr)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("set TimeZone = 'UTC'")
    con.execute(FIXTURE_SQL.read_text())
    print(f"rendered {FIXTURE_SQL.relative_to(HERE.parent)} with DuckDB {duckdb.__version__}")
    for table in TABLES:
        cols = con.execute(
            "select column_name, data_type from information_schema.columns "
            "where table_schema = 'thelook_ecommerce' and table_name = ? order by ordinal_position",
            [table],
        ).fetchall()
        select = ", ".join(
            f'cast("{name}" as varchar) as "{name}"' if dtype.upper().startswith("GEOMETRY") else f'"{name}"'
            for name, dtype in cols
        )
        path = OUT / f"{table}.parquet"
        con.execute(f"copy (select {select} from thelook_ecommerce.{table}) to '{path}' (format parquet)")
        n = con.execute(f"select count(*) from read_parquet('{path}')").fetchone()[0]
        print(f"  {table:<22} {n:>6} rows  {len(cols)} columns  -> {path.relative_to(HERE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
