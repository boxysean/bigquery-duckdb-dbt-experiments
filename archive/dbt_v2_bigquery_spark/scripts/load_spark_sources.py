#!/usr/bin/env python3
"""Load the REAL bigquery-public-data.thelook_ecommerce into Spark (SPEC section 5).

    python3 scripts/load_spark_sources.py                          # all seven tables
    python3 scripts/load_spark_sources.py --tables distribution_centers,orders
    python3 scripts/load_spark_sources.py --rest                   # tabledata.list, no Storage API

The Spark target must read the same real rows the BigQuery target reads. Per table:

  1. read the table with the BigQuery Python client: `client.list_rows(table)`, a
     TABLE READ (Storage Read API by default, `tabledata.list` with --rest), never a
     query job, so no query bytes are billed and maximum_bytes_billed is not involved;
  2. stream the Arrow batches to target/spark_sources/<table>/part-00000.parquet;
  3. register every table in the Spark catalog the models read, THROUGH the running
     Thrift Server (beeline -> jdbc:hive2://127.0.0.1:10000): the server owns the
     Derby metastore, so it is never opened from a second process.
     Measured on Spark 4.2.0: `CREATE OR REPLACE TABLE ... USING PARQUET` is refused
     on the session catalog (UNSUPPORTED_FEATURE.TABLE_OPERATION "does not support
     REPLACE TABLE"), so each table is `DROP TABLE IF EXISTS` + `CREATE TABLE ...
     USING PARQUET LOCATION`. The table is external: the drop never deletes the files.
  4. read back through Spark: count(*) and, for every TIMESTAMP column, min/max as
     unix_micros and typeof.

Gates (exit 1 on any): rows written == BigQuery numRows (table metadata) == Spark
count(*); every timestamp column's Spark min/max == the min/max of the instants as
BigQuery delivered them (so the load moved no instant); every timestamp column is
`timestamp` (an instant) on Spark, not `timestamp_ntz`. Exit 2: no BigQuery
credential. Everything printed also goes to the log (--log).

Credential: BQ_KEYFILE (a service-account key file; default
~/.config/gcp/coreychimpbot-sa.json when it exists), else GOOGLE_APPLICATION_CREDENTIALS.
The key path is never printed. Runs under ~/.local/spark/venv/bin/python (it re-execs
itself there when started with an interpreter lacking the BigQuery client).
"""

import argparse
import datetime as dt
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPARK_PREFIX = Path(os.environ.get("SPARK_PREFIX", Path.home() / ".local" / "spark"))
SPARK_PY = SPARK_PREFIX / "venv" / "bin" / "python"
BEELINE = SPARK_PREFIX / "venv" / "bin" / "beeline"
JDBC_URL = "jdbc:hive2://127.0.0.1:10000/default"
SPARK_ENDPOINT = ("127.0.0.1", 10000)
DATA_PROJECT = os.environ.get("BQ_DATA_PROJECT", "bigquery-public-data")
BILLING_PROJECT = os.environ.get("BQ_BILLING_PROJECT", "coreychimpbot")
DATASET = "thelook_ecommerce"
SPARK_DATABASE = "thelook_ecommerce"   # the spark source renders `thelook_ecommerce`.`<table>`
TABLES = ["distribution_centers", "products", "users", "inventory_items", "orders",
          "order_items", "events"]
OUT_DIR = ROOT / "target" / "spark_sources"
DEFAULT_LOG = OUT_DIR / "load_spark_sources.log"
DEFAULT_KEYFILE = Path.home() / ".config" / "gcp" / "coreychimpbot-sa.json"
PROGRESS_SECS = 5.0

EXIT_OK, EXIT_FAIL, EXIT_NO_CREDENTIAL = 0, 1, 2

try:
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    from google.cloud import bigquery
    from google.oauth2 import service_account
except ImportError:
    # Compare venvs, not executables: every venv's python symlinks to the same base one.
    if Path(sys.prefix).resolve() != SPARK_PY.parent.parent.resolve() and SPARK_PY.exists():
        os.execv(str(SPARK_PY), [str(SPARK_PY), __file__, *sys.argv[1:]])
    print(f"the BigQuery client / pyarrow is not importable from {sys.executable} "
          f"(nor is {SPARK_PY} there). Run scripts/install_prereqs.sh.")
    sys.exit(EXIT_FAIL)


class Tee:
    """Everything printed goes to stdout and to the log file."""

    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = open(path, "w", encoding="utf-8")
        self.stdout = sys.stdout

    def write(self, text):
        self.stdout.write(text)
        self.file.write(text)

    def flush(self):
        self.stdout.flush()
        self.file.flush()


def instant(micros):
    if micros is None:
        return "NULL"
    t = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(microseconds=micros)
    return t.isoformat(timespec="microseconds").replace("+00:00", "Z")


def credentials():
    """(credentials, label) or (None, reason)."""
    keyfile = os.environ.get("BQ_KEYFILE") or (str(DEFAULT_KEYFILE) if DEFAULT_KEYFILE.exists() else "")
    source = "BQ_KEYFILE" if os.environ.get("BQ_KEYFILE") else "the default key file"
    if not keyfile:
        keyfile = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
        source = "GOOGLE_APPLICATION_CREDENTIALS"
    if not keyfile:
        return None, ("no BigQuery credential: set BQ_KEYFILE to a service-account key file "
                      "(or GOOGLE_APPLICATION_CREDENTIALS); nothing was loaded")
    if not Path(keyfile).is_file():
        return None, f"{source} names a file that does not exist; nothing was loaded"
    creds = service_account.Credentials.from_service_account_file(
        keyfile, scopes=["https://www.googleapis.com/auth/cloud-platform"])
    return creds, f"service-account key file from {source}"


def pull(client, bqs, name):
    """Read one table into Parquet. Returns a dict of what was measured."""
    table = client.get_table(f"{DATA_PROJECT}.{DATASET}.{name}")
    ts_cols = [f.name for f in table.schema if f.field_type == "TIMESTAMP"]
    other_time = [f"{f.name} ({f.field_type})" for f in table.schema if f.field_type in ("DATETIME", "TIME")]
    out = OUT_DIR / name
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    path = out / "part-00000.parquet"

    print(f"[{name}] BigQuery numRows {table.num_rows:,}, {table.num_bytes:,} bytes, "
          f"{len(table.schema)} columns; timestamp columns: {', '.join(ts_cols) or 'none'}")
    if other_time:
        print(f"[{name}] NOTE zone-less columns (arrive as timestamp_ntz / string): {', '.join(other_time)}")

    started = last = time.monotonic()
    rows, writer = 0, None
    bounds = {c: [None, None] for c in ts_cols}
    try:
        for batch in client.list_rows(table).to_arrow_iterable(bqstorage_client=bqs):
            if batch.num_rows == 0:
                continue
            if writer is None:
                writer = pq.ParquetWriter(path, batch.schema)
            writer.write_batch(batch)
            rows += batch.num_rows
            for c in ts_cols:
                mm = pc.min_max(batch.column(c).cast(pa.int64()))
                lo, hi = mm["min"].as_py(), mm["max"].as_py()
                b = bounds[c]
                if lo is not None:
                    b[0] = lo if b[0] is None else min(b[0], lo)
                    b[1] = hi if b[1] is None else max(b[1], hi)
            now = time.monotonic()
            if now - last >= PROGRESS_SECS:
                pct = 100.0 * rows / table.num_rows if table.num_rows else 100.0
                print(f"[{name}]   {rows:,} / {table.num_rows:,} rows ({pct:.0f}%) after {now - started:.0f}s")
                last = now
    finally:
        if writer is not None:
            writer.close()
    secs = time.monotonic() - started
    if writer is None:
        print(f"[{name}] WARNING no rows read; no Parquet file written")
    else:
        print(f"[{name}] wrote {rows:,} rows to {path.relative_to(ROOT)} "
              f"({path.stat().st_size:,} bytes) in {secs:.1f}s")
        # The instant contract, on disk: a UTC-adjusted Arrow timestamp is written as a
        # Parquet TIMESTAMP(isAdjustedToUTC=true), which Spark reads as TIMESTAMP (an
        # instant), not TIMESTAMP_NTZ. The Spark read-back below proves the same thing.
        schema = pq.read_schema(path)
        for c in ts_cols:
            t = schema.field(c).type
            print(f"[{name}]   {c}: Parquet/Arrow type {t}")
    return {"name": name, "num_rows": table.num_rows, "written": rows, "dir": out,
            "ts_cols": ts_cols, "bq_bounds": bounds, "secs": secs, "empty": writer is None}


def register_and_read_back(results):
    """One beeline session: register every table, then read counts and bounds back."""
    sql = [f"CREATE DATABASE IF NOT EXISTS {SPARK_DATABASE};"]
    for r in results:
        if r["empty"]:
            continue
        loc = str(r["dir"].resolve()).replace("'", "\\'")
        sql.append(f"DROP TABLE IF EXISTS {SPARK_DATABASE}.{r['name']};")
        sql.append(f"CREATE TABLE {SPARK_DATABASE}.{r['name']} USING PARQUET LOCATION '{loc}';")
    for r in results:
        if r["empty"]:
            continue
        parts = ["'@@ROW'", f"'{r['name']}'", "cast(count(*) as string)"]
        for c in r["ts_cols"]:
            parts += [f"coalesce(cast(unix_micros(min(`{c}`)) as string), 'NULL')",
                      f"coalesce(cast(unix_micros(max(`{c}`)) as string), 'NULL')",
                      f"typeof(min(`{c}`))"]
        sql.append(f"SELECT concat_ws('|', {', '.join(parts)}) FROM {SPARK_DATABASE}.{r['name']};")
    sql.append("SELECT concat_ws('|', '@@TZ', current_timezone());")

    with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False) as f:
        f.write("\n".join(sql) + "\n")
        sql_file = f.name
    env = dict(os.environ, JAVA_HOME=str(SPARK_PREFIX / "jdk"),
               SPARK_HOME=subprocess.run([str(SPARK_PY), "-c", "import os, pyspark; print(os.path.dirname(pyspark.__file__))"],
                                         capture_output=True, text=True, check=True).stdout.strip())
    cmd = [str(BEELINE), "-u", JDBC_URL, "-n", os.environ.get("USER", "spark"), "--silent=true",
           "--showHeader=false", "--outputformat=tsv2", "-f", sql_file]
    print(f"[spark] registering {sum(not r['empty'] for r in results)} table(s) as "
          f"{SPARK_DATABASE}.<table> through {JDBC_URL} (beeline)")
    started = time.monotonic()
    proc = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    os.unlink(sql_file)
    print(f"[spark] beeline exit {proc.returncode} in {time.monotonic() - started:.1f}s")
    if proc.returncode != 0:
        errors = [l for l in proc.stdout.splitlines() if l.startswith("Error:")]
        for line in (errors or proc.stdout.splitlines()[-15:])[:5]:
            print("    " + line[:300])
        return None, None
    back, tz = {}, None
    for line in proc.stdout.splitlines():
        if "@@ROW|" in line:
            fields = line[line.index("@@ROW|"):].strip().split("|")
            back[fields[1]] = fields[2:]
        elif "@@TZ|" in line:
            tz = line[line.index("@@TZ|"):].strip().split("|")[1]
    return back, tz


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tables", help="comma-separated subset of: " + ",".join(TABLES))
    parser.add_argument("--rest", action="store_true",
                        help="read with tabledata.list instead of the Storage Read API (slower)")
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG, help=f"default {DEFAULT_LOG.relative_to(ROOT)}")
    args = parser.parse_args()

    tables = TABLES
    if args.tables:
        tables = [t.strip() for t in args.tables.split(",") if t.strip()]
        unknown = [t for t in tables if t not in TABLES]
        if unknown:
            print(f"unknown table(s): {', '.join(unknown)}; choose from {', '.join(TABLES)}")
            return EXIT_FAIL

    sys.stdout = Tee(args.log)
    print(f"load_spark_sources: {DATA_PROJECT}.{DATASET} -> Spark {SPARK_DATABASE}.<table> "
          f"({len(tables)} table(s): {', '.join(tables)}); log {args.log}")

    creds, label = credentials()
    if creds is None:
        print(label)
        return EXIT_NO_CREDENTIAL
    try:
        with socket.create_connection(SPARK_ENDPOINT, timeout=3):
            pass
    except OSError:
        print("FAIL  no Spark Thrift Server on 127.0.0.1:10000: run scripts/start_spark.sh first")
        return EXIT_FAIL

    client = bigquery.Client(project=BILLING_PROJECT, credentials=creds)
    bqs = None
    if not args.rest:
        from google.cloud import bigquery_storage
        bqs = bigquery_storage.BigQueryReadClient(credentials=creds)
    print(f"credential: {label}; billing project {BILLING_PROJECT}; read path: "
          + ("tabledata.list (REST)" if args.rest else "Storage Read API") + " (table reads, no query job)\n")

    results, started = [], time.monotonic()
    for i, name in enumerate(tables, 1):
        print(f"--- table {i}/{len(tables)}: {name}")
        results.append(pull(client, bqs, name))
        print()

    back, tz = register_and_read_back(results)
    if back is None:
        print("FAIL  registering the tables in Spark failed (beeline errors above)")
        return EXIT_FAIL
    print(f"[spark] session time zone: {tz}\n")

    failures = []
    print(f"{'table':22s} {'BigQuery numRows':>17s} {'rows written':>13s} {'Spark count':>12s}  status")
    for r in results:
        got = back.get(r["name"])
        spark_n = int(got[0]) if got else None
        ok = r["written"] == r["num_rows"] and (r["empty"] or spark_n == r["num_rows"])
        if not ok:
            failures.append(f"{r['name']}: numRows {r['num_rows']}, written {r['written']}, Spark {spark_n}")
        print(f"{r['name']:22s} {r['num_rows']:>17,} {r['written']:>13,} "
              f"{spark_n if spark_n is None else format(spark_n, ','):>12}  {'ok' if ok else 'MISMATCH'}")
    print()

    print("timestamp columns (instants, UTC): BigQuery as delivered vs Spark read-back")
    moved = 0
    for r in results:
        got = back.get(r["name"]) or []
        for k, c in enumerate(r["ts_cols"]):
            bq_lo, bq_hi = r["bq_bounds"][c]
            sp = got[1 + 3 * k: 4 + 3 * k]
            if len(sp) == 3:
                sp_lo, sp_hi = (None if v == "NULL" else int(v) for v in sp[:2])
                sp_type = sp[2]
            else:
                sp_lo, sp_hi, sp_type = None, None, "not read back"
            same = (bq_lo, bq_hi) == (sp_lo, sp_hi)
            typed = sp_type == "timestamp"
            moved += not same
            if not same:
                failures.append(f"{r['name']}.{c}: BigQuery [{instant(bq_lo)}, {instant(bq_hi)}] "
                                f"vs Spark [{instant(sp_lo)}, {instant(sp_hi)}]")
            if not typed:
                failures.append(f"{r['name']}.{c}: Spark type is {sp_type}, not timestamp (an instant)")
            print(f"  {r['name']}.{c}: min {instant(bq_lo)}  max {instant(bq_hi)}  "
                  f"Spark {sp_type}: {'same instants' if same else 'MOVED'}")
    n_ts = sum(len(r["ts_cols"]) for r in results)
    print(f"instants moved by the load: {'none' if moved == 0 else moved} "
          f"({n_ts} timestamp column(s) checked; Spark session time zone {tz})")
    if tz != "UTC":
        failures.append(f"Spark session time zone is {tz}, not UTC")
    print(f"\ntotal wall time {time.monotonic() - started:.1f}s")

    if failures:
        print(f"\nFAIL  {len(failures)} problem(s):")
        for f in failures:
            print("  " + f)
        return EXIT_FAIL
    print(f"\nOK  {len(results)} table(s) loaded; row counts match BigQuery numRows; no instant moved")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
