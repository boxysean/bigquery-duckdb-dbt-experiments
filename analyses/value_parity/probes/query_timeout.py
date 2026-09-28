"""Probe: does BigQueryLeg.query survive a jobs.query answer with jobComplete = false?

    BQ_KEYFILE=... DBT_ENV=rows python3 analyses/value_parity/probes/query_timeout.py

The fresh value-parity run (analyses/value_parity/fresh/) left int_order_items__enriched
"not_measured" with "list index out of range": jobs.query waits timeoutMs (default
10 s), then answers jobComplete=false with no rows, and measure_of took rows[0] of an
empty list. This forces the incomplete answer (timeoutMs=1, query cache off) and shows
(1) the raw first answer has no rows, (2) BigQueryLeg.query now returns the same row as
a normal cached run.
"""
import importlib.util
import json
import os
import time
import urllib.request
from datetime import datetime, timezone

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
spec = importlib.util.spec_from_file_location("parity", f"{REPO}/scripts/parity.py")
parity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parity)

bq = parity.BigQueryLeg(os.environ["BQ_KEYFILE"], "coreychimpbot")
src = f"`coreychimpbot.{parity.SCHEMA}.int_order_items__enriched`"
print(f"# query_timeout.py  {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}"
      f"  relation {src}")
cols = bq.schema_of(src)
sql = parity.metrics_sql(bq.engine, src, [(n, k) for n, k, _ in cols])
forced = {"timeoutMs": 1, "useQueryCache": False}

body = {"query": sql, "useLegacySql": False,
        "maximumBytesBilled": str(parity.MAX_BYTES), **forced}
req = urllib.request.Request(parity.BQ_API.format(project="coreychimpbot"),
                             data=json.dumps(body).encode())
req.add_header("Authorization", "Bearer " + bq.token)
req.add_header("Content-Type", "application/json")
with urllib.request.urlopen(req, timeout=900) as resp:
    raw = json.loads(resp.read().decode())
print(f"raw jobs.query, timeoutMs=1: jobComplete={raw.get('jobComplete')}"
      f" rows={len(raw.get('rows', []))}  -> the old code's rows[0] raises IndexError")

_, polled = bq.query(sql, extra=forced)
_, normal = bq.query(sql)
a = parity._normalise(polled[0], cols)
b = parity._normalise(normal[0], cols)
print(f"BigQueryLeg.query, timeoutMs=1 (polled): __rows={a['__rows']}")
print(f"BigQueryLeg.query, default:              __rows={b['__rows']}")
print(f"every metric equal: {a == b} ({len(a)} metrics)")

# How long the query takes against jobs.query's default wait (timeoutMs 10 s), with the
# query cache off so the job really runs: first the raw first answer, then the full call.
nocache = {"query": sql, "useLegacySql": False, "useQueryCache": False,
           "maximumBytesBilled": str(parity.MAX_BYTES)}
req = urllib.request.Request(parity.BQ_API.format(project="coreychimpbot"),
                             data=json.dumps(nocache).encode())
req.add_header("Authorization", "Bearer " + bq.token)
req.add_header("Content-Type", "application/json")
t0 = time.monotonic()
with urllib.request.urlopen(req, timeout=900) as resp:
    raw = json.loads(resp.read().decode())
print(f"raw jobs.query, cache off, default timeoutMs: {time.monotonic() - t0:.1f} s,"
      f" jobComplete={raw.get('jobComplete')} rows={len(raw.get('rows', []))}"
      f" cacheHit={raw.get('cacheHit')}")
t0 = time.monotonic()
_, uncached = bq.query(sql, extra={"useQueryCache": False})
print(f"BigQueryLeg.query, cache off, default timeoutMs: {time.monotonic() - t0:.1f} s,"
      f" __rows={parity._normalise(uncached[0], cols)['__rows']}")
