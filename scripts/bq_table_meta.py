#!/usr/bin/env python3
"""Print BigQuery's own row and byte counts for tables, from table metadata.

    python3 scripts/bq_table_meta.py orders users ...   # table|numRows|numBytes

Used by scripts/load_duckdb_real_sources.sh to check each local copy against what
BigQuery says the table holds. It calls the REST `tables.get` endpoint, which reads
metadata: it is not a query job, so it bills nothing and cannot hit
`maximum_bytes_billed`.

Environment: BQ_KEYFILE (a service-account key file; required, never printed),
BQ_DATA_PROJECT (default bigquery-public-data), BQ_DATASET (default
thelook_ecommerce). Any failure -> a message on stderr and exit 1.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

URL = ("https://bigquery.googleapis.com/bigquery/v2/projects/{project}"
       "/datasets/{dataset}/tables/{table}")


def _access_token(key: str) -> str:
    # One implementation of the JWT exchange in this repository: parity.py's.
    spec = importlib.util.spec_from_file_location(
        "parity", Path(__file__).resolve().parent / "parity.py")
    parity = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parity)
    return parity.access_token(key)


def main(tables) -> int:
    key = os.environ.get("BQ_KEYFILE")
    if not key or not Path(key).is_file():
        print("bq_table_meta: BQ_KEYFILE is not set or is not a file", file=sys.stderr)
        return 1
    project = os.environ.get("BQ_DATA_PROJECT", "bigquery-public-data")
    dataset = os.environ.get("BQ_DATASET", "thelook_ecommerce")
    try:
        token = _access_token(key)
    except Exception as e:  # noqa: BLE001
        print(f"bq_table_meta: could not obtain an access token: {e}", file=sys.stderr)
        return 1
    for table in tables:
        req = urllib.request.Request(URL.format(project=project, dataset=dataset,
                                                table=table))
        req.add_header("Authorization", "Bearer " + token)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                meta = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            print(f"bq_table_meta: {project}.{dataset}.{table}: HTTP {e.code}: "
                  f"{e.read().decode()[:400]}", file=sys.stderr)
            return 1
        print(f"{table}|{meta.get('numRows', '')}|{meta.get('numBytes', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
