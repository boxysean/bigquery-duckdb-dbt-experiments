"""Probe: what is in the BigQuery dataset the BigQuery leg writes to, right now?

    BQ_KEYFILE=... python3 analyses/value_parity/probes/bq_state.py

Prints the dataset's existence/location and every relation it holds with the row
count the BigQuery API reports, so a measurement can say whether the leg it reads
is the one the of-record value-parity run wrote (2026-09-27) or something newer.
"""
import importlib.util
import json
import os
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
spec = importlib.util.spec_from_file_location("parity", f"{REPO}/scripts/parity.py")
parity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parity)

PROJECT = "coreychimpbot"
DATASET = f"experiments_{os.environ.get('DBT_ENV', 'dev')}"
bq = parity.BigQueryLeg(os.environ["BQ_KEYFILE"], PROJECT)


def api(path):
    req = urllib.request.Request(
        f"https://bigquery.googleapis.com/bigquery/v2/projects/{PROJECT}{path}")
    req.add_header("Authorization", "Bearer " + bq.token)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


try:
    meta = api(f"/datasets/{DATASET}")
    print(f"dataset {PROJECT}.{DATASET}: location {meta.get('location')}")
except Exception as exc:
    print(f"dataset {PROJECT}.{DATASET}: NOT FOUND ({exc})")
    raise SystemExit(1)

tables = api(f"/datasets/{DATASET}/tables").get("tables", [])
print(f"{len(tables)} relations")
rows = []
for t in tables:
    table_id = t["tableReference"]["tableId"]
    try:
        full = api(f"/datasets/{DATASET}/tables/{table_id}")
        rows.append((table_id, t["type"], full.get("numRows", "?"),
                     full.get("numBytes") or "?", full.get("creationTime"),
                     full.get("lastModifiedTime")))
    except Exception as exc:
        rows.append((table_id, t["type"], "-", "-", "-", str(exc)[:60]))
for name, typ, nrows, nbytes, created, modified in sorted(rows):
    print(f"  {name:36s} {typ:8s} {nrows:>9} rows {nbytes:>12} B"
          f"  created {created}  modified {modified}")