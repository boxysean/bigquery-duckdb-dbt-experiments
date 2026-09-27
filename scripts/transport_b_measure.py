#!/usr/bin/env python3
"""Transport B: BigQuery -> Cloud Storage (Parquet) -> DuckDB, measured. And back.

This is the harness behind analyses/transport_b/README.md. Where Transport A
(scripts/transport_a_measure.py) runs everything inside one DuckDB CLI process,
Transport B is two systems talking through a bucket, so this harness drives:

  * BigQuery over the REST API (extract/load/query jobs) — stdlib + the `openssl`
    CLI only, no google-* packages, same as scripts/parity.py and the Transport A
    harness. The service-account key is used as a JWT signing key; its contents are
    never printed or written to a log;
  * Cloud Storage over the JSON API with the same credentials: list, get, download,
    upload, delete;
  * the DuckDB CLI for the read-back side, one process per scenario, with wall time
    measured here and peak RSS taken from /usr/bin/time -v.

Every scenario writes analyses/transport_b/logs/<key>.log containing the exact SQL or
HTTP request as run, and the raw response or output. Nothing here decides pass/fail on
its own: scenarios whose whole point is an error are marked expect_failure and are
recorded with the error text.

Usage
-----
    BQ_KEYFILE=/path/to/service-account.json python3 scripts/transport_b_measure.py
    python3 scripts/transport_b_measure.py --list
    python3 scripts/transport_b_measure.py --only b02 b07 b09
    python3 scripts/transport_b_measure.py --skip-cleanup    # leave the objects behind
"""

from __future__ import annotations

import argparse
import base64
import csv
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BASE = REPO / "analyses" / "transport_b"
SQL_DIR = BASE / "sql"
LOG_DIR = BASE / "logs"
TMP = Path(os.environ.get("TRANSPORT_B_TMP", str(Path(tempfile.gettempdir()) / "transport_b")))

DEFAULT_BILLING = "coreychimpbot"
DEFAULT_BUCKET = "coreychimpbot-experiments"
DEFAULT_DATA_PROJECT = "bigquery-public-data"
TIME_BIN = "/usr/bin/time"

# Pricing, from Google's own pages, read 2026-09-27. Quoted in the log of scenario b30
# and in the README; nothing below is a guess.
PRICING = {
    "bigquery_on_demand_usd_per_tib": 6.25,
    "bigquery_free_tib_per_month": 1.0,
    "bigquery_minimum_bytes_billed": 10 * 1024 * 1024,
    "extract_job": "free (batch export, shared slot pool, up to 50 TiB/day)",
    "storage_read_api_usd_per_tib": 1.10,
    "storage_read_api_free_tib_per_month": 300.0,
    "gcs_standard_us_multi_region_usd_per_gib_month": 0.0260,
    "gcs_internet_egress_usd_per_gib": 0.12,
    "gcs_class_a_ops_usd_per_1000": 0.01,
    "gcs_class_b_ops_usd_per_1000": 0.0004,
    "sources": [
        "https://cloud.google.com/bigquery/pricing#data-extraction",
        "https://cloud.google.com/storage/pricing",
    ],
}


# --------------------------------------------------------------------------- token
def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def access_token(keyfile: str, force: bool = False) -> str:
    """A service-account access token, via a self-signed JWT (stdlib + openssl)."""
    cache = TMP / "token.json"
    if not force and cache.exists():
        try:
            payload = json.loads(cache.read_text())
            if payload.get("keyfile") == keyfile and payload.get("expires_at", 0) > time.time() + 60:
                return payload["token"]
        except Exception:
            pass
    with open(keyfile) as fh:
        info = json.load(fh)
    token_url = "https://oauth2.googleapis.com/token"
    scope = ("https://www.googleapis.com/auth/bigquery "
             "https://www.googleapis.com/auth/devstorage.read_write "
             "https://www.googleapis.com/auth/cloud-platform")
    now = int(time.time())
    claims = _b64(json.dumps({
        "iss": info["client_email"], "scope": scope, "aud": token_url,
        "iat": now, "exp": now + 3600}).encode())
    signing_input = f"{_b64(json.dumps({'alg': 'RS256', 'typ': 'JWT'}).encode())}.{claims}"
    with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as kf:
        kf.write(info["private_key"])
        pem = kf.name
    try:
        signature = subprocess.run(["openssl", "dgst", "-sha256", "-sign", pem],
                                   input=signing_input.encode(), capture_output=True,
                                   check=True).stdout
    finally:
        os.unlink(pem)
    body = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": f"{signing_input}.{_b64(signature)}"}).encode()
    with urllib.request.urlopen(urllib.request.Request(token_url, data=body), timeout=60) as r:
        out = json.loads(r.read().decode())
    TMP.mkdir(parents=True, exist_ok=True)
    token = out["access_token"]
    cache.write_text(json.dumps({"keyfile": keyfile, "token": token,
                                 "expires_at": now + out.get("expires_in", 3600) - 120}))
    return token


# ----------------------------------------------------------------------- the client
class Client:
    """BigQuery + Cloud Storage over REST, token kept in memory only."""

    def __init__(self, keyfile: str, project: str, bucket: str):
        self.keyfile = keyfile
        self.project = project
        self.bucket = bucket

    # -- HTTP ---------------------------------------------------------------
    def request(self, method, url, body=None, raw_body=None, content_type=None,
                extra_headers=None, timeout=300):
        headers = {"Authorization": "Bearer " + access_token(self.keyfile)}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        elif raw_body is not None:
            data = raw_body
            if content_type:
                headers["Content-Type"] = content_type
        if extra_headers:
            headers.update(extra_headers)
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                payload = r.read()
                return r.status, (json.loads(payload) if payload else {})
        except urllib.error.HTTPError as e:
            raw = e.read().decode(errors="replace")
            try:
                return e.code, json.loads(raw)
            except Exception:
                return e.code, {"raw": raw}

    # -- BigQuery -----------------------------------------------------------
    def bq(self, path):
        return f"https://bigquery.googleapis.com/bigquery/v2/projects/{self.project}{path}"

    def run_query(self, sql, location="US", dry_run=False, max_bytes=1_000_000_000_000):
        """jobs.query: for SELECTs and dry runs. Returns (status, job, rows)."""
        body = {"query": sql, "useLegacySql": False, "location": location,
                "maximumBytesBilled": str(max_bytes), "dryRun": dry_run}
        status, out = self.request("POST", self.bq("/queries"), body=body)
        rows = []
        if status == 200 and not dry_run:
            names = [f["name"] for f in out.get("schema", {}).get("fields", [])]
            for row in out.get("rows", []):
                rows.append({n: c.get("v") for n, c in zip(names, row.get("f", []))})
        return status, out, rows

    def run_job(self, sql, location="US", max_bytes=1_000_000_000_000, poll_s=2.0,
                timeout_s=1800):
        """jobs.insert then poll: for EXPORT DATA, scripts, DDL. Returns (status, job)."""
        body = {"configuration": {"query": {"query": sql, "useLegacySql": False,
                                            "maximumBytesBilled": str(max_bytes)}},
                "jobReference": {"projectId": self.project, "location": location}}
        status, out = self.request("POST", self.bq("/jobs"), body=body)
        if status != 200:
            return status, out
        ref = out["jobReference"]
        jid, loc = ref["jobId"], ref.get("location", location)
        started = time.time()
        while True:
            status, job = self.request("GET", self.bq(f"/jobs/{jid}?location={loc}"))
            if status != 200:
                return status, job
            if job.get("status", {}).get("state") == "DONE":
                return 200, job
            if time.time() - started > timeout_s:
                return 408, {"jobReference": ref, "status": {"state": "POLL_TIMEOUT"}}
            time.sleep(poll_s)

    def run_load_job(self, source_uris, destination_table, source_format="PARQUET",
                     write_disposition="WRITE_TRUNCATE", location="US",
                     schema=None, autodetect=False):
        config = {"load": {"sourceUris": source_uris, "sourceFormat": source_format,
                           "destinationTable": destination_table,
                           "writeDisposition": write_disposition,
                           "autodetect": autodetect}}
        if schema:
            config["load"]["schema"] = schema
        body = {"configuration": config,
                "jobReference": {"projectId": self.project, "location": location}}
        status, out = self.request("POST", self.bq("/jobs"), body=body)
        if status != 200:
            return status, out
        ref = out["jobReference"]
        jid, loc = ref["jobId"], ref.get("location", location)
        while True:
            status, job = self.request("GET", self.bq(f"/jobs/{jid}?location={loc}"))
            if status != 200:
                return status, job
            if job.get("status", {}).get("state") == "DONE":
                return 200, job
            time.sleep(2.0)

    def table(self, table_ref):
        return f"https://bigquery.googleapis.com/bigquery/v2/{table_ref}"

    def table_meta(self, project, dataset, table):
        status, out = self.request(
            "GET", f"{self.bq('/datasets/' + dataset + '/tables/' + table)}")
        return status, out

    # -- Cloud Storage ------------------------------------------------------
    def gcs(self, path):
        return f"https://storage.googleapis.com/storage/v1{path}"

    def list_objects(self, prefix):
        objects, token = [], None
        while True:
            url = self.gcs(f"/b/{self.bucket}/o?maxResults=1000&prefix={urllib.parse.quote(prefix)}")
            if token:
                url += f"&pageToken={token}"
            status, out = self.request("GET", url)
            if status != 200:
                raise RuntimeError(f"object list failed: {status} {out}")
            objects += out.get("items", [])
            token = out.get("nextPageToken")
            if not token:
                return objects

    def delete_objects(self, names):
        for name in names:
            self.request("DELETE", self.gcs(f"/b/{self.bucket}/o/{urllib.parse.quote(name, safe='')}"))

    def object_meta(self, name):
        return self.request("GET", self.gcs(f"/b/{self.bucket}/o/{urllib.parse.quote(name, safe='')}"))

    def object_bytes(self, name):
        url = self.gcs(f"/b/{self.bucket}/o/{urllib.parse.quote(name, safe='')}?alt=media")
        status, _ = -1, None
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + access_token(self.keyfile)})
        with urllib.request.urlopen(req, timeout=900) as r:
            return r.read()

    def download(self, name, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        data = self.object_bytes(name)
        Path(path).write_bytes(data)
        return len(data)

    def upload(self, local_path, name):
        data = Path(local_path).read_bytes()
        url = (f"https://storage.googleapis.com/upload/storage/v1/b/{self.bucket}/o"
               f"?uploadType=media&name={urllib.parse.quote(name, safe='')}")
        return self.request("POST", url, raw_body=data, content_type="application/octet-stream")


# ------------------------------------------------------------------------- harness
class Harness:
    def __init__(self, client: Client, subs: dict, run_id: str):
        self.client = client
        self.subs = subs
        self.run_id = run_id
        self.results: list[dict] = []
        self.state: dict = {}
        self.jobs: list[dict] = []

    # -- logging ------------------------------------------------------------
    def redact(self, text: str) -> str:
        for placeholder, value in self.subs.items():
            if value and placeholder in ("__TOKEN__", "__SA_PATH__"):
                text = text.replace(value, placeholder)
        # belt and braces: never write anything that looks like an access token
        return re.sub(r"ya29\.[A-Za-z0-9_\-\.]+", "__TOKEN__", text)

    def log(self, key, header, body):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        path = LOG_DIR / f"{key}.log"
        text = "\n".join(f"# {line}" for line in header) + f"\n\n{body}\n"
        path.write_text(self.redact(text))
        return str(path.relative_to(REPO))

    def record(self, key, title, log_path, wall, status, metrics=None, extra=None):
        entry = {"key": key, "title": title, "log": log_path, "wall_s": round(wall, 2),
                 "status": status, "metrics": metrics or {}}
        if extra:
            entry.update(extra)
        self.results.append(entry)
        return entry

    # -- runners ------------------------------------------------------------
    def render(self, sql_file):
        text = (SQL_DIR / sql_file).read_text()
        for placeholder, value in self.subs.items():
            text = text.replace(placeholder, str(value))
        return text

    def duckdb(self, key, title, sql_file, expect_failure=False, timeouts=600):
        sql = self.render(sql_file)
        TMP.mkdir(parents=True, exist_ok=True)
        time_path = TMP / f"{key}.time"
        cmd = [TIME_BIN, "-v", "-o", str(time_path), duckdb_cli(), "-init", "/dev/null", ":memory:"]
        started = time.monotonic()
        proc = subprocess.run(cmd, input=sql, text=True, capture_output=True, timeout=timeouts)
        wall = time.monotonic() - started
        rss_kb = None
        if time_path.exists():
            match = re.search(r"Maximum resident set size \(kbytes\): (\d+)", time_path.read_text())
            if match:
                rss_kb = int(match.group(1))
        combined = proc.stdout + proc.stderr
        status = "ok" if proc.returncode == 0 else "error"
        log = self.log(key, [
            f"{key}: {title}",
            f"sql: analyses/transport_b/sql/{sql_file} (placeholders substituted at run time;",
            f"     __SA_PATH__ stands for the service-account key path, __TOKEN__ for a",
            f"     short-lived access token — neither value is ever written to this log)",
            f"wall {wall:.2f}s  exit {proc.returncode}  peak RSS {rss_kb} kB",
            f"command: {' '.join(cmd)} <<'SQL'",
        ], f"{sql}\n# ---- output ----\n{combined}")
        metrics = {"exit_code": proc.returncode, "peak_rss_kb": rss_kb,
                   "errors_expected": expect_failure,
                   "error_lines": [line for line in combined.splitlines()
                                   if re.match(r"^(Binder|Parser|Invalid|Permission|Catalog|IO|"
                                               r"Conversion|Transaction|INTERNAL|FATAL|HTTP|Out of|"
                                               r"Constraint) ", line)],
                   "rows": parse_tables(combined)}
        return self.record(key, title, log, wall, status, metrics)

    def bq_job(self, key, title, sql_file, expect_failure=False, max_bytes=1_000_000_000_000):
        sql = self.render(sql_file)
        started = time.monotonic()
        status, job = self.client.run_job(sql, max_bytes=max_bytes)
        wall = time.monotonic() - started
        stats = (job.get("statistics") or {}).get("query", {})
        error_messages = job_errors(job)
        ok = status == 200 and not error_messages
        body = json.dumps(job, indent=1, default=str)
        log = self.log(key, [
            f"{key}: {title}",
            f"sql: analyses/transport_b/sql/{sql_file}",
            f"wall {wall:.2f}s  http {status}  job {job.get('jobReference', {}).get('jobId')}",
            f"job state {job.get('status', {}).get('state')}  statementType {stats.get('statementType')}",
            f"expected to fail: {expect_failure}",
        ], f"{sql}\n# ---- job resource ----\n{body}")
        metrics = {
            "http_status": status,
            "job_id": job.get("jobReference", {}).get("jobId"),
            "statement_type": stats.get("statementType"),
            "total_bytes_processed": to_int(stats.get("totalBytesProcessed")),
            "total_bytes_billed": to_int(stats.get("totalBytesBilled")),
            "total_slot_ms": to_int(stats.get("totalSlotMs")),
            "duration_ms": job_duration_ms(job),
            "export_file_count": to_int((stats.get("exportDataStatistics") or {}).get("fileCount")),
            "export_row_count": to_int((stats.get("exportDataStatistics") or {}).get("rowCount")),
            "cache_hit": stats.get("cacheHit"),
            "errors": error_messages,
            "error_lines": error_messages,
            "errors_expected": expect_failure,
        }
        self.jobs.append({"key": key, **{k: metrics[k] for k in
                                         ("total_bytes_processed", "total_bytes_billed",
                                          "statement_type")}})
        return self.record(key, title, log, wall, "ok" if ok else "error", metrics)

    def bq_query(self, key, title, sql_file, expect_failure=False, dry_run=False):
        sql = self.render(sql_file)
        started = time.monotonic()
        status, out, rows = self.client.run_query(sql, dry_run=dry_run)
        wall = time.monotonic() - started
        stats = out.get("statistics", {}).get("query", {}) if status == 200 else {}
        if dry_run and status == 200:
            # a dry-run response carries the prediction at the top level
            stats = {"totalBytesProcessed": out.get("totalBytesProcessed"),
                     "cacheHit": out.get("cacheHit"),
                     "statementType": "DRY_RUN"}
        errors = out.get("errors", []) or []
        ok = status == 200 and not errors
        log = self.log(key, [
            f"{key}: {title}",
            f"sql: analyses/transport_b/sql/{sql_file}",
            f"dry run: {dry_run}  wall {wall:.2f}s  http {status}",
            f"expected to fail: {expect_failure}",
        ], f"{sql}\n# ---- result ----\n{json.dumps(out, indent=1, default=str)[:20000]}")
        metrics = {
            "http_status": status,
            "dry_run": dry_run,
            "total_bytes_processed": to_int(stats.get("totalBytesProcessed")),
            "cache_hit": stats.get("cacheHit"),
            "statement_type": stats.get("statementType"),
            "rows_returned": len(rows),
            "first_row": rows[0] if rows else None,
            "errors": [e.get("message") for e in errors],
            "error_lines": [e.get("message") for e in errors],
            "errors_expected": expect_failure,
        }
        if dry_run and to_int(stats.get("totalBytesProcessed")) is not None:
            self.jobs.append({"key": key, "total_bytes_processed": to_int(stats.get("totalBytesProcessed")),
                              "total_bytes_billed": None, "statement_type": "DRY_RUN"})
        return self.record(key, title, log, wall, "ok" if ok else "error", metrics)


def to_int(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def job_duration_ms(job):
    stats = (job.get("statistics") or {})
    created = to_int(stats.get("creationTime")) or to_int((job.get("statistics") or {}).get("startTime"))
    end = to_int(stats.get("endTime"))
    if created and end:
        return end - created
    return None


def job_errors(job):
    """BigQuery reports a failed job in status.errors, status.errorResult, or both."""
    if not isinstance(job, dict):
        return []
    status = job.get("status", {}) or {}
    errors = list(status.get("errors", []) or [])
    error_result = status.get("errorResult")
    if error_result and not errors:
        errors.append(error_result)
    return [e.get("message") for e in errors if isinstance(e, dict)]


def parse_tables(text):
    """Pull the ASCII tables the DuckDB CLI prints into lists of rows."""
    lines = text.splitlines()
    rows, current, header = [], [], None
    for line in lines:
        if line.startswith("┌") or line.startswith("├"):
            current, header = [], None
            continue
        if line.startswith("└"):
            if current:
                rows.append(current)
            current = []
            continue
        if line.startswith("│"):
            cells = [c.strip() for c in line.strip("│").split("│")]
            if header is None:
                header = cells
                current = []
            else:
                current.append(dict(zip(header, cells)))
    return rows


def duckdb_cli() -> str:
    for candidate in (os.environ.get("DUCKDB_CLI"), shutil.which("duckdb"),
                      str(Path.home() / ".local" / "bin" / "duckdb")):
        if candidate and Path(candidate).exists():
            return candidate
    sys.exit("no duckdb CLI found: set DUCKDB_CLI or put duckdb on the path")


# ------------------------------------------------------------------------ scenarios
def object_summary(objects):
    sizes = sorted(int(o["size"]) for o in objects)
    return {
        "files": len(objects),
        "total_bytes": sum(sizes),
        "max_bytes": sizes[-1] if sizes else 0,
        "min_bytes": sizes[0] if sizes else 0,
        "median_bytes": sizes[len(sizes) // 2] if sizes else 0,
        "names": [o["name"] for o in sorted(objects, key=lambda x: x["name"])],
    }


def object_listing(objects):
    return "\n".join(f"{o['name']}  {int(o['size'])} bytes  {o.get('updated', '')}"
                     for o in sorted(objects, key=lambda x: x["name"]))


def export_scenario(h, key, title, sql_file, prefix, expect_failure=False):
    sql = h.render(sql_file)
    started = time.monotonic()
    status, job = h.client.run_job(sql)
    wall = time.monotonic() - started
    stats = (job.get("statistics") or {}).get("query", {})
    errors = list(job_errors(job))
    objects, list_error = [], None
    try:
        objects = h.client.list_objects(prefix)
    except Exception as exc:  # noqa: BLE001
        list_error = str(exc)
    summary = object_summary(objects)
    h.state[f"{key}_objects"] = objects
    log = h.log(key, [
        f"{key}: {title}",
        f"sql: analyses/transport_b/sql/{sql_file}",
        f"wall (job insert + poll) {wall:.2f}s  http {status}  "
        f"job {job.get('jobReference', {}).get('jobId')}",
        f"statementType {stats.get('statementType')}  state {job.get('status', {}).get('state')}",
        f"expected to fail: {expect_failure}",
        f"objects under gs://{h.client.bucket}/{prefix}: {summary['files']}"
        + (f" (list failed: {list_error})" if list_error else ""),
    ], f"{sql}\n# ---- job resource ----\n{json.dumps(job, indent=1, default=str)}\n"
       f"# ---- objects ----\n{object_listing(objects)}")
    if list_error:
        errors.append(f"object list: {list_error}")
    metrics = {
        "http_status": status,
        "job_id": job.get("jobReference", {}).get("jobId"),
        "statement_type": stats.get("statementType"),
        "job_duration_ms": job_duration_ms(job),
        "total_bytes_processed": to_int(stats.get("totalBytesProcessed")),
        "total_bytes_billed": to_int(stats.get("totalBytesBilled")),
        "total_slot_ms": to_int(stats.get("totalSlotMs")),
        "export_file_count": to_int((stats.get("exportDataStatistics") or {}).get("fileCount")),
        "export_row_count": to_int((stats.get("exportDataStatistics") or {}).get("rowCount")),
        "objects": summary,
        "errors": errors,
        "error_lines": errors,
        "errors_expected": expect_failure,
    }
    h.jobs.append({"key": key, "total_bytes_processed": metrics["total_bytes_processed"],
                   "total_bytes_billed": metrics["total_bytes_billed"],
                   "statement_type": metrics["statement_type"]})
    return h.record(key, title, log, wall, "ok" if not errors else "error", metrics)


def urls_for(h, key):
    objects = h.state.get(f"{key}_objects")
    if objects is None:
        return None
    return ["https://storage.googleapis.com/%s/%s" % (h.client.bucket, o["name"])
            for o in sorted(objects, key=lambda x: x["name"])]


def duck_url_list(h, key):
    urls = urls_for(h, key)
    if urls is None:
        return None
    return "[" + ", ".join("'%s'" % u for u in urls) + "]"


def skip(h, key, title, reason):
    log = h.log(key, [f"{key}: {title}", f"SKIPPED: {reason}"], "")
    return h.record(key, title, log, 0.0, "skipped", {"skip_reason": reason})


def b01_gcs_access(h):
    key, title = "b01", "the GCS permission surface the service account actually has"
    started = time.monotonic()
    client = h.client
    probes = [
        ("buckets.list", f"https://storage.googleapis.com/storage/v1/b?project={client.project}"),
        ("bucket.get", client.gcs(f"/b/{client.bucket}")),
        ("objects.list", client.gcs(f"/b/{client.bucket}/o?maxResults=5")),
    ]
    lines, metrics = [], {}
    first_object = None
    for label, url in probes:
        status, out = client.request("GET", url)
        lines.append(f"GET {url}\n  -> {status} {json.dumps(out)[:400]}")
        metrics[label] = status
        if label == "objects.list" and status == 200 and out.get("items"):
            first_object = out["items"][0]["name"]
    if first_object:
        url = client.gcs(f"/b/{client.bucket}/o/{urllib.parse.quote(first_object, safe='')}")
        status, out = client.request("GET", url)
        lines.append(f"GET {url}\n  -> {status} {json.dumps(out)[:400]}")
        metrics["object.get"] = status
    else:
        lines.append("no object to fetch yet, so object.get is not probed here (the first "
                     "export's scenario lists objects, which needs the same permission class)")
        metrics["object.get"] = None
    wall = time.monotonic() - started
    log = h.log(key, [
        f"{key}: {title}",
        "No object or bucket was modified. The point is the smallest possible",
        "credential footprint: enough to list, read and write objects, nothing else.",
    ], "\n\n".join(lines))
    return h.record(key, title, log, wall,
                    "ok", {"http_status": metrics, "error_lines": []})


def b06_gs(h):
    return h.duckdb("b06", "read_parquet over gs:// without HMAC keys (no secret)",
                    "b06_gs_no_hmac.sql", expect_failure=True)


def b06b_gs_fake(h):
    return h.duckdb("b06b", "read_parquet over gs:// with a TYPE gcs secret holding placeholder keys",
                    "b06b_gs_fake_hmac.sql", expect_failure=True)


def b07_http(h):
    return h.duckdb("b07", "read_parquet over the GCS XML API with an http secret carrying a bearer token",
                    "b07_http_bearer_read.sql")


def b07b_scoped(h):
    return h.duckdb("b07b", "the same bearer-token secret with SCOPE set",
                    "b07b_http_bearer_scoped.sql", expect_failure=True)


def b07c_no_secret(h):
    return h.duckdb("b07c", "control: same URL, no secret at all",
                    "b07c_http_no_secret.sql", expect_failure=True)


def b07d_bogus(h):
    return h.duckdb("b07d", "control: same URL, a bogus bearer token",
                    "b07d_http_bogus_token.sql", expect_failure=True)


def b09_multi(h):
    urls = duck_url_list(h, "b04")
    if urls is None:
        return skip(h, "b09", "read the multi-file export over HTTPS", "b04 did not run in this invocation")
    h.subs["__URLS__"] = urls
    result = h.duckdb("b09", "read all %d objects of the b04 export over HTTPS as one DuckDB list"
                      % len(urls_for(h, "b04")), "b09_read_multi_https.sql")
    result["metrics"]["urls"] = len(urls_for(h, "b04"))
    return result


def b03b_usa_names_read(h):
    urls = duck_url_list(h, "b03")
    if urls is None:
        return skip(h, "b03b", "read the usa_names export", "b03 did not run in this invocation")
    h.subs["__URLS__"] = urls
    return h.duckdb("b03b", "read the usa_names export (5,552,452 rows) — Transport A's head-to-head table",
                    "b09_read_multi_https.sql")


def b10_local(h):
    key, title = "b10", "the same export pulled down with the GCS JSON API, then read locally"
    objects = h.state.get("b04_objects")
    if objects is None:
        return skip(h, key, title, "b04 did not run in this invocation")
    local = TMP / "b10"
    if local.exists():
        shutil.rmtree(local)
    local.mkdir(parents=True)
    started = time.monotonic()
    total = 0
    timings = []
    for o in sorted(objects, key=lambda x: x["name"]):
        t0 = time.monotonic()
        size = h.client.download(o["name"], local / Path(o["name"]).name)
        total += size
        timings.append(time.monotonic() - t0)
    download_wall = time.monotonic() - started
    h.subs["__LOCAL_DIR__"] = str(local)
    result = h.duckdb(key, title, "b10_read_local.sql")
    result["metrics"].update({
        "objects_downloaded": len(objects), "bytes_downloaded": total,
        "download_wall_s": round(download_wall, 2),
        "download_median_file_s": round(sorted(timings)[len(timings) // 2], 3) if timings else None,
        "local_dir": str(local),
    })
    return result


def b17_csv_vs_parquet(h):
    key, title = "b17", "the same rows as CSV (b15) and as Parquet (b16), read side by side"
    parquet_urls, csv_urls = urls_for(h, "b16"), urls_for(h, "b15")
    if not parquet_urls or not csv_urls:
        return skip(h, key, title, "b15/b16 did not run in this invocation")
    h.subs["__PARQUET_URL__"] = parquet_urls[0]
    h.subs["__CSV_URL__"] = csv_urls[0]
    result = h.duckdb(key, title, "b17_csv_vs_parquet.sql")
    result["metrics"]["parquet_url"] = parquet_urls
    result["metrics"]["csv_url"] = csv_urls
    return result


def b17b_json_csv(h):
    key, title = "b17b", "the JSON column after the CSV round trip (b14b)"
    urls = urls_for(h, "b14b")
    if not urls:
        return skip(h, key, title, "b14b produced no objects")
    h.subs["__JSON_CSV_URL__"] = urls[0]
    result = h.duckdb(key, title, "b17b_json_csv_read.sql")
    result["metrics"]["json_csv_url"] = urls
    return result


def b18_types(h):
    urls = duck_url_list(h, "b13")
    if urls is None or not urls_for(h, "b13"):
        return skip(h, "b18", "read the nested/repeated Parquet export", "b13 produced no objects")
    h.subs["__URLS__"] = urls
    return h.duckdb("b18", "read the nested/repeated Parquet export", "b18_types_parquet_read.sql")


def b18b_edge(h):
    urls = duck_url_list(h, "b13b")
    if urls is None or not urls_for(h, "b13b"):
        return skip(h, "b18b", "read the BIGNUMERIC/GEOGRAPHY Parquet export",
                    "b13b produced no objects")
    h.subs["__URLS__"] = urls
    return h.duckdb("b18b", "read the BIGNUMERIC/GEOGRAPHY Parquet export", "b18b_edge_parquet_read.sql")


def b24_row_order(h):
    key, title = "b24", "row order evidence: three identical exports and one ORDER BY, compared"
    # A, B and D are three runs of the SAME unordered SQL (b22, b22b, b22c); C is the run
    # with ORDER BY (b23). Two files are compared from each unordered run, which is enough
    # to see the shard boundary move; the ordered run writes a single file.
    prefixes = {"A1": ("b22", 0), "A2": ("b22", 1), "B1": ("b22b", 0), "B2": ("b22b", 1),
                "D1": ("b22c", 0), "D2": ("b22c", 1), "C1": ("b23", 0)}
    local = TMP / "b24"
    if local.exists():
        shutil.rmtree(local)
    local.mkdir(parents=True)
    downloaded = {}
    for slot, (source, index) in prefixes.items():
        urls = sorted(urls_for(h, source) or [])
        if not urls:
            return skip(h, key, title, f"{source} produced no objects")
        index = min(index, len(urls) - 1)
        name = urls[index].split(f"{h.client.bucket}/", 1)[1]
        path = local / f"{slot}.parquet"
        h.client.download(name, path)
        downloaded[slot] = str(path)
        h.subs[f"__{slot}__"] = str(path)
    result = h.duckdb(key, title, "b24_row_order_evidence.sql")
    result["metrics"]["files"] = downloaded
    result["metrics"]["object_counts"] = {k: len(urls_for(h, k) or []) for k in ("b22", "b22b", "b23")}
    return result


def b26_reverse(h):
    h.subs["__PARQUET_OUT__"] = str(TMP / "reverse_src.parquet")
    h.subs["__DUMP_OUT__"] = str(TMP / "reverse_src_dump.csv")
    result = h.duckdb("b26", "the reverse direction, step 1: DuckDB writes Parquet",
                      "b26_reverse_write_parquet.sql")
    parquet = Path(h.subs["__PARQUET_OUT__"])
    result["metrics"]["parquet_path"] = str(parquet)
    result["metrics"]["parquet_bytes"] = parquet.stat().st_size if parquet.exists() else None
    return result


def b27_upload_load(h):
    key, title = "b27", "the reverse direction, step 2: upload the Parquet, load it, read the schema back"
    parquet = Path(h.subs.get("__PARQUET_OUT__", str(TMP / "reverse_src.parquet")))
    if not parquet.exists():
        return skip(h, key, title, "b26 did not run in this invocation")
    object_name = f"{h.subs['__PREFIX__']}/b27/reverse_src.parquet"
    started = time.monotonic()
    status, out = h.client.upload(parquet, object_name)
    upload_wall = time.monotonic() - started
    destination = {"projectId": h.client.project, "datasetId": "experiments_dev",
                   "tableId": "transport_b_reverse"}
    started = time.monotonic()
    lstatus, job = h.client.run_load_job(
        [f"gs://{h.client.bucket}/{object_name}"], destination, source_format="PARQUET",
        write_disposition="WRITE_TRUNCATE")
    load_wall = time.monotonic() - started
    stats = (job.get("statistics") or {}).get("load", {})
    mstatus, meta = h.client.table_meta(h.client.project, "experiments_dev", "transport_b_reverse")
    errors = job_errors(job)
    log = h.log(key, [
        f"{key}: {title}",
        f"upload: POST /upload/storage/v1/b/{h.client.bucket}/o?uploadType=media&name={object_name}"
        f"  local {parquet.name} ({parquet.stat().st_size} bytes)  -> {status}  {upload_wall:.2f}s",
        f"load: jobs.insert configuration.load sourceUris=[gs://{h.client.bucket}/{object_name}]"
        f" sourceFormat=PARQUET writeDisposition=WRITE_TRUNCATE  -> {lstatus}  {load_wall:.2f}s",
        f"destination: {h.client.project}.experiments_dev.transport_b_reverse",
        "the table metadata below is what BigQuery inferred from the Parquet file:",
        "compare it with the DuckDB DESCRIBE in the b26 log",
    ], f"# ---- upload response ----\n{json.dumps(out, indent=1, default=str)[:2000]}\n"
       f"# ---- load job ----\n{json.dumps(job, indent=1, default=str)[:6000]}\n"
       f"# ---- destination table metadata ----\n{json.dumps(meta, indent=1, default=str)[:6000]}")
    metrics = {
        "upload_http_status": status,
        "object": object_name,
        "upload_wall_s": round(upload_wall, 2),
        "load_http_status": lstatus,
        "load_job_id": job.get("jobReference", {}).get("jobId") if isinstance(job, dict) else None,
        "load_wall_s": round(load_wall, 2),
        "load_output_rows": to_int(stats.get("outputRows")),
        "load_output_bytes": to_int(stats.get("outputBytes")),
        "table_schema": [{"name": f["name"], "type": f["type"], "mode": f.get("mode")}
                         for f in (meta.get("schema", {}) or {}).get("fields", [])] if mstatus == 200 else None,
        "table_num_rows": to_int(meta.get("numRows")) if mstatus == 200 else None,
        "errors": errors,
        "error_lines": errors,
    }
    return h.record(key, title, log, upload_wall + load_wall, "ok" if not errors else "error", metrics)


def b29_verify(h):
    key, title = "b29", "does the loaded table match what DuckDB wrote? (values, not just counts)"
    dump_path = Path(h.subs.get("__DUMP_OUT__", str(TMP / "reverse_src_dump.csv")))
    if not dump_path.exists():
        return skip(h, key, title, "b26 did not run in this invocation")
    with dump_path.open() as fh:
        source_rows = {int(r["id"]): {k: (None if v == "\\N" else v) for k, v in r.items()}
                       for r in csv.DictReader(fh)}

    select = (
        "SELECT id, CAST(n AS STRING) AS n, CAST(d AS STRING) AS d, s, CAST(b AS STRING) AS b, "
        "CAST(dt AS STRING) AS dt, CAST(ts AS STRING) AS ts, CAST(tstz AS STRING) AS tstz, "
        "TO_HEX(bin) AS bin, TO_JSON_STRING(arr_i) AS arr_i, TO_JSON_STRING(st) AS st, "
        "TO_JSON_STRING(arr_st) AS arr_st FROM `%s.experiments_dev.%s` ORDER BY id")

    report, metrics = [], {}
    for table in ("transport_b_reverse", "transport_b_reverse_ext"):
        mstatus, meta = h.client.table_meta(h.client.project, "experiments_dev", table)
        schema = ([{"name": f["name"], "type": f["type"], "mode": f.get("mode")}
                   for f in (meta.get("schema", {}) or {}).get("fields", [])]
                  if mstatus == 200 else None)
        status, out, rows = h.client.run_query(select % (h.client.project, table))
        if status != 200:
            report.append(f"--- {table}: query failed {status} {json.dumps(out)[:300]}")
            metrics[table] = {"query_status": status, "rows": None}
            continue
        loaded = {int(r["id"]): r for r in rows}
        columns = ["n", "d", "s", "b", "dt", "ts", "tstz", "bin", "arr_i", "st", "arr_st"]
        mismatches = {c: [] for c in columns}
        for rid, src in source_rows.items():
            dst = loaded.get(rid)
            if dst is None:
                mismatches["n"].append((rid, "missing row", None))
                continue
            for column in columns:
                if not values_equal(column, src[column], dst[column]):
                    if len(mismatches[column]) < 3:
                        mismatches[column].append((rid, src[column], dst[column]))
        metrics[table] = {
            "query_status": status,
            "declared_schema": schema,
            "source_rows": len(source_rows),
            "loaded_rows": len(loaded),
            "ids_match": set(source_rows) == set(loaded),
            "mismatch_counts": {c: len(v) for c, v in mismatches.items()},
            "mismatch_examples": {c: v for c, v in mismatches.items() if v},
        }
        # the shape of the loaded list column: a Parquet LIST arrives as a RECORD with a
        # `list` field rather than as an ARRAY<T>, so the obvious BigQuery SQL fails.
        shape = {}
        plain = (f"SELECT arr_i[OFFSET(0)] AS first_element "
                 f"FROM `{h.client.project}.experiments_dev.{table}` WHERE id = 1")
        wrapped = (f"SELECT arr_i.list[OFFSET(0)].element AS first_element "
                   f"FROM `{h.client.project}.experiments_dev.{table}` WHERE id = 1")
        for label, sql in (("arr_i[OFFSET(0)]", plain), ("arr_i.list[OFFSET(0)].element", wrapped)):
            s2, out2, rows2 = h.client.run_query(sql)
            shape[label] = {"status": s2,
                            "value": rows2[0].get("first_element") if (s2 == 200 and rows2) else None,
                            "error": None if s2 == 200 else ("; ".join(str(e) for e in job_errors(out2))
                                                            or json.dumps(out2)[:200])}
        metrics[table]["list_column_shape"] = shape
        report.append(f"--- {table} list-column shape\n" + json.dumps(shape, indent=1, default=str))
        report.append(f"--- {table}\n" + json.dumps(metrics[table], indent=1, default=str))
    log = h.log(key, [
        f"{key}: {title}",
        "source: the DuckDB dump b26 wrote (values cast to text in DuckDB)",
        "destination: the two BigQuery tables loaded from the same Parquet file —",
        "  transport_b_reverse      loaded by this harness' own upload + jobs.insert",
        "  transport_b_reverse_ext  loaded by the extension's bigquery_load (b28)",
        "comparison: 1,000 rows, every column, values parsed rather than string-matched",
        "  (decimals as Decimal, JSON columns parsed with json.loads, BYTES via hex)",
    ], "\n\n".join(report))
    return h.record(key, title, log, 0.0, "ok", metrics)


def bq_unwrap(value):
    """BigQuery returns Parquet lists as RECORD<list ARRAY<RECORD<element T>>>; DuckDB's
    to_json returns the bare list. Unwrap the BigQuery shape so the two are comparable."""
    if isinstance(value, dict):
        if set(value) == {"element"}:
            return bq_unwrap(value["element"])
        if set(value) == {"list"}:
            return [bq_unwrap(e) for e in value["list"]]
        return {k: bq_unwrap(v) for k, v in value.items()}
    if isinstance(value, list):
        return [bq_unwrap(e) for e in value]
    return value


def as_json(text):
    if text is None:
        return None
    text = str(text).strip()
    if text in ("", "null", "NULL"):
        return None
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        return json.loads(text.replace("'", '"'))


def values_equal(column, left, right):
    # nested values first: BigQuery renders a NULL RECORD as the string "null", so the
    # generic None check below would call that a mismatch.
    if column in ("arr_i", "st", "arr_st"):
        return bq_unwrap(as_json(right)) == as_json(left)
    if left is None or right is None:
        return (left is None) == (right is None)
    if column == "n":
        from decimal import Decimal, InvalidOperation
        try:
            return Decimal(str(left)) == Decimal(str(right))
        except InvalidOperation:
            return False
    if column == "d":
        return float(left) == float(right)
    if column == "b":
        return (left.strip().lower() in ("true", "1")) == (right.strip().lower() in ("true", "1"))
    if column == "bin":
        return left.lower() == right.lower()
    if column in ("ts", "tstz"):
        return same_instant(left, right)
    return normalize(left) == normalize(right)


DT_RE = re.compile(
    r"^(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d):(\d\d)(?:\.(\d+))?(?:\s*(?:Z|([+-])(\d\d):?(\d\d)?))?$")


def parse_instant(text):
    """A datetime string with or without a zone. Naive means UTC (BigQuery TIMESTAMP)."""
    match = DT_RE.match(str(text).strip())
    if not match:
        return None
    year, month, day, hour, minute, second, frac, sign, off_h, off_m = match.groups()
    micro = int((frac or "0").ljust(6, "0")[:6])
    stamp = dt.datetime(int(year), int(month), int(day), int(hour), int(minute), int(second),
                        micro, tzinfo=dt.timezone.utc)
    if sign:
        delta = dt.timedelta(hours=int(off_h), minutes=int(off_m or 0))
        stamp -= delta if sign == "+" else -delta
    return stamp


def same_instant(left, right):
    a, b = parse_instant(left), parse_instant(right)
    if a is None or b is None:
        return normalize(left) == normalize(right)
    return a == b


def normalize(text):
    """Timestamps and dates: 'T' vs ' ', trailing zeros, explicit UTC offsets."""
    value = str(text).strip().replace("T", " ").replace("Z", "+00")
    value = re.sub(r"([+-]\d\d):?(\d\d)$", r"\1:\2", value)
    if "." in value:
        head, _, tail = value.partition(".")
        frac = re.match(r"(\d+)([+-]\d\d:\d\d)?$", tail)
        if frac:
            value = head + "." + frac.group(1).rstrip("0").ljust(1, "0") + (frac.group(2) or "")
    return value


def b30_cost(h):
    key, title = "b30", "what this run cost, from the job statistics and Google's price pages"
    processed = sum(j["total_bytes_processed"] or 0 for j in h.jobs)
    billed = sum(j["total_bytes_billed"] or 0 for j in h.jobs)
    exports = [j for j in h.jobs if j.get("statement_type") == "EXPORT_DATA"]
    objects = []
    try:
        objects = h.client.list_objects(f"{h.subs['__PREFIX__']}/")
    except Exception as exc:  # noqa: BLE001
        pass
    written = sum(int(o["size"]) for o in objects)
    tib = 1024 ** 4
    gib = 1024 ** 3
    report = {
        "jobs_seen": len(h.jobs),
        "export_data_jobs": len(exports),
        "bytes_processed_total": processed,
        "bytes_billed_total": billed,
        "gcs_bytes_written_and_still_present": written,
        "gcs_objects": len(objects),
        "on_demand_cost_usd_this_run": round(max(0.0, billed / tib - 0) * PRICING["bigquery_on_demand_usd_per_tib"], 6),
        "note_on_free_tier": (
            "the first 1 TiB of query data per month is free, so the real invoice impact of "
            "this run is $0 unless the shared 1 TiB/month account allowance is already spent; "
            "the number above is what it costs at list price if it is not covered"),
        "gcs_storage_usd_per_month_if_left": round(written / gib * PRICING["gcs_standard_us_multi_region_usd_per_gib_month"], 5),
        "gcs_egress_if_read_to_this_box_usd": round(written / gib * PRICING["gcs_internet_egress_usd_per_gib"], 5),
        "pricing_constants": PRICING,
    }
    log = h.log(key, [
        f"{key}: {title}",
        "Pricing constants below come from Google's pages (read 2026-09-27); the byte counts",
        "come from the job resources this harness recorded, not from an estimate.",
        "Batch export jobs (extract jobs, i.e. the extension's bigquery_extract) are free;",
        "EXPORT DATA statements are billed as queries. Both are in this run.",
    ], json.dumps(report, indent=1, default=str))
    return h.record(key, title, log, 0.0, "ok", report)


def b31_cleanup(h):
    key, title = "b31", "cleanup: leave the bucket and the dataset as they were found"
    prefix = f"{h.subs['__PREFIX__']}/"
    objects = h.client.list_objects(prefix)
    h.client.delete_objects([o["name"] for o in objects])
    remaining = h.client.list_objects(prefix)
    drops = []
    for table in ("transport_b_types", "transport_b_types_flat", "transport_b_types_json",
                  "transport_b_types_edge", "transport_b_reverse", "transport_b_reverse_ext"):
        sql = f"DROP TABLE IF EXISTS `{h.client.project}.experiments_dev.{table}`"
        status, out, _ = h.client.run_query(sql)
        drops.append(f"{table}: {status}")
    status, out, rows = h.client.run_query(
        "SELECT table_name FROM `%s.experiments_dev`.INFORMATION_SCHEMA.TABLES ORDER BY table_name"
        % h.client.project)
    tables = [r["table_name"] for r in rows]
    log = h.log(key, [
        f"{key}: {title}",
        f"deleted {len(objects)} objects under gs://{h.client.bucket}/{prefix}",
        "dropped the five probe tables this harness created in experiments_dev",
    ], f"deleted: {json.dumps([o['name'] for o in objects], indent=1)}\n"
       f"objects remaining under the prefix: {len(remaining)}\n"
       f"drops: {drops}\n"
       f"tables left in experiments_dev ({len(tables)}): {tables}")
    return h.record(key, title, log, 0.0, "ok", {
        "objects_deleted": len(objects), "objects_remaining": len(remaining),
        "tables_left": tables, "drops": drops})


SCENARIOS = [
    ("b01", b01_gcs_access),
    ("b02", lambda h: export_scenario(h, "b02", "EXPORT DATA one mart to GCS as Parquet",
                                      "b02_export_mart.sql", f"{h.subs['__PREFIX__']}/b02/")),
    ("b03", lambda h: export_scenario(h, "b03", "EXPORT DATA usa_names (5,552,452 rows) — the Transport A table",
                                      "b03_export_usa_names.sql", f"{h.subs['__PREFIX__']}/b03/")),
    ("b03b", b03b_usa_names_read),
    ("b04", lambda h: export_scenario(h, "b04", "EXPORT DATA an 8.0 GB table: what the 1 GB-per-file limit does",
                                      "b04_export_split.sql", f"{h.subs['__PREFIX__']}/b04/")),
    ("b05", lambda h: h.bq_query("b05", "the same shape as b04, dry run: predicted bytes before spending any",
                                 "b05_export_dry_run.sql", dry_run=True)),
    ("b06", b06_gs),
    ("b06b", b06b_gs_fake),
    ("b07", b07_http),
    ("b07b", b07b_scoped),
    ("b07c", b07c_no_secret),
    ("b07d", b07d_bogus),
    ("b08", lambda h: h.duckdb("b08", "wildcards are not a thing on generic HTTPS URLs",
                               "b08_http_glob.sql", expect_failure=True)),
    ("b08b", lambda h: h.duckdb("b08b", "the flag DuckDB suggests for b08",
                                "b08b_http_glob_flag.sql", expect_failure=True)),
    ("b09", b09_multi),
    ("b10", b10_local),
    ("b11", lambda h: h.duckdb("b11", "the exported mart Parquet, as DuckDB sees it",
                               "b11_mart_typeof.sql")),
    ("b12", lambda h: h.bq_job("b12", "create the type-probe tables", "b12_create_type_tables.sql")),
    ("b13", lambda h: export_scenario(h, "b13", "EXPORT DATA the nested/repeated type table as Parquet",
                                      "b13_export_types_parquet.sql", f"{h.subs['__PREFIX__']}/b13/")),
    ("b13b", lambda h: export_scenario(h, "b13b", "EXPORT DATA BIGNUMERIC + GEOGRAPHY as Parquet",
                                       "b13b_export_edge_parquet.sql", f"{h.subs['__PREFIX__']}/b13b/")),
    ("b13c", lambda h: export_scenario(h, "b13c", "EXPORT DATA JSON as Parquet",
                                       "b13c_export_json_parquet.sql", f"{h.subs['__PREFIX__']}/b13c/",
                                       expect_failure=True)),
    ("b14", lambda h: export_scenario(h, "b14", "the documented refusal: nested/repeated data to CSV",
                                      "b14_export_types_csv_nested.sql", f"{h.subs['__PREFIX__']}/b14/",
                                      expect_failure=True)),
    ("b14b", lambda h: export_scenario(h, "b14b", "the CSV export that IS allowed for JSON (b13c's control)",
                                       "b14b_export_json_csv.sql", f"{h.subs['__PREFIX__']}/b14b/")),
    ("b15", lambda h: export_scenario(h, "b15", "the CSV export that IS allowed (flat table)",
                                      "b15_export_flat_csv.sql", f"{h.subs['__PREFIX__']}/b15/")),
    ("b16", lambda h: export_scenario(h, "b16", "the same flat rows as Parquet, for the comparison",
                                      "b16_export_flat_parquet.sql", f"{h.subs['__PREFIX__']}/b16/")),
    ("b17", b17_csv_vs_parquet),
    ("b17b", b17b_json_csv),
    ("b18", b18_types),
    ("b18b", b18b_edge),
    ("b19", lambda h: h.bq_job("b19", "two EXPORT DATA statements in one request (one script, two child jobs)",
                               "b19_two_export_statements.sql")),
    ("b20", lambda h: export_scenario(h, "b20", "the workaround: a script with two EXPORT DATA statements",
                                      "b20_script_two_exports.sql", f"{h.subs['__PREFIX__']}/b20/")),
    ("b21", lambda h: export_scenario(h, "b21", "the wrong workaround: UNION ALL merges the tables into one file set",
                                      "b21_union_all_one_job.sql", f"{h.subs['__PREFIX__']}/b21/")),
    ("b22", lambda h: export_scenario(h, "b22", "row order, export A (no ORDER BY)",
                                      "b22_row_order_a.sql", f"{h.subs['__PREFIX__']}/b22/a-")),
    ("b22b", lambda h: export_scenario(h, "b22b", "row order, export B (identical SQL, second run)",
                                       "b22b_row_order_b.sql", f"{h.subs['__PREFIX__']}/b22/b-")),
    ("b22c", lambda h: export_scenario(h, "b22c", "row order, export D (identical SQL, third run)",
                                       "b22c_row_order_d.sql", f"{h.subs['__PREFIX__']}/b22/d-")),
    ("b23", lambda h: export_scenario(h, "b23", "row order with ORDER BY temp (and what the sort does to the file count)",
                                      "b23_row_order_order_by.sql", f"{h.subs['__PREFIX__']}/b23/")),
    ("b24", b24_row_order),
    ("b25", lambda h: h.duckdb("b25", "the extension's own forward path: bigquery_extract",
                               "b25_extension_extract.sql")),
    ("b26", b26_reverse),
    ("b27", b27_upload_load),
    ("b28", lambda h: h.duckdb("b28", "the extension's own reverse path: bigquery_load from a DuckDB table",
                               "b28_extension_load.sql")),
    ("b29", b29_verify),
    ("b30", b30_cost),
    ("b31", b31_cleanup),
]

TITLES = {key: (fn.__name__ if hasattr(fn, "__name__") else key) for key, fn in SCENARIOS}


def write_results(h, cli, run_id, started_at, finished_at):
    # A partial run (`--only a b c`) must not throw away the other scenarios' records: the
    # committed results.json is the whole suite, and iterating on one scenario is normal.
    # Records are merged by key, in scenario order; the header describes the run that last
    # touched the file, and `runs` lists every run that contributed.
    previous = {}
    runs = []
    path = BASE / "results.json"
    if path.exists():
        try:
            old = json.loads(path.read_text())
            previous = {r["key"]: r for r in old.get("scenarios", [])}
            runs = list(old.get("runs", []))
            if not runs and old.get("generated_at"):
                runs = [{"finished_at": old["generated_at"], "run_id": old.get("run_id")}]
        except (ValueError, KeyError):
            previous = {}
    fresh = {r["key"]: r for r in h.results}
    merged = []
    for key, _fn in SCENARIOS:
        if key in fresh:
            merged.append(fresh[key])
        elif key in previous:
            merged.append(previous[key])
    runs.append({"run_id": run_id, "started_at": started_at, "finished_at": finished_at,
                 "scenarios": sorted(fresh)})
    payload = {
        "generated_at": finished_at,
        "started_at": started_at,
        "run_id": run_id,
        "runs": runs,
        "duckdb_cli": cli,
        "duckdb_version": subprocess.run([cli, "--version"], capture_output=True,
                                          text=True).stdout.strip(),
        "billing_project": h.client.project,
        "bucket": h.client.bucket,
        "prefix": h.subs["__PREFIX__"],
        "host_cpus": os.cpu_count(),
        "scenarios": merged,
        "jobs": h.jobs,
        "pricing": PRICING,
    }
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n")
    h.results = merged  # the table below is the merged record, not this run's slice

    lines = [
        "# Transport B measurements (generated)",
        "",
        f"Generated by `scripts/transport_b_measure.py` at {finished_at} with "
        f"`{payload['duckdb_version']}`.",
        f"Billing project `{payload['billing_project']}`, bucket `gs://{payload['bucket']}/"
        f"{payload['prefix']}/`, {payload['host_cpus']} CPUs on the box.",
        "Wall time is measured by the harness around the job or DuckDB process; peak RSS is "
        "`/usr/bin/time -v` for the DuckDB process. Logs: `analyses/transport_b/logs/`.",
        "",
    ]
    if len(payload["runs"]) > 1:
        first = payload["runs"][0]
        lines.append(f"Records merged from {len(payload['runs'])} runs: this table was last "
                     f"refreshed {finished_at} for {len(fresh)} scenario(s); the rest are "
                     f"carried over from the run of {first.get('finished_at')} "
                     f"(`runs` in results.json lists them all).")
        lines.append("")
    lines += [
        "| # | scenario | wall s | peak RSS MiB | exit/status | files | bytes out | bytes processed |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in h.results:
        m = r["metrics"]
        rss = f"{m['peak_rss_kb'] / 1024:.0f}" if m.get("peak_rss_kb") else "—"
        files = m.get("objects", {}).get("files", m.get("export_file_count"))
        out_bytes = m.get("objects", {}).get("total_bytes")
        processed = m.get("total_bytes_processed")
        lines.append(
            f"| {r['key']} | {r['title']} | {r['wall_s']:.2f} | {rss} | {r['status']}"
            + (f" (expected)" if m.get("errors_expected") else "")
            + f" | {files if files is not None else '—'} | "
              f"{out_bytes if out_bytes is not None else '—'} | "
              f"{processed if processed is not None else '—'} |")
    lines.append("")
    (BASE / "results.md").write_text("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="*", metavar="KEY", help="run only these scenario keys")
    parser.add_argument("--list", action="store_true", help="list scenarios and exit")
    parser.add_argument("--skip-cleanup", action="store_true", help="do not run b31")
    parser.add_argument("--bucket", default=os.environ.get("GCS_BUCKET", DEFAULT_BUCKET))
    parser.add_argument("--billing-project", default=os.environ.get("BQ_BILLING_PROJECT", DEFAULT_BILLING))
    parser.add_argument("--data-project", default=os.environ.get("BQ_DATA_PROJECT", DEFAULT_DATA_PROJECT))
    parser.add_argument("--prefix", default=os.environ.get("TRANSPORT_B_PREFIX", "transport_b"))
    parser.add_argument("--max-bytes-billed", type=int,
                        default=int(os.environ.get("BQ_MAX_BYTES_BILLED", 50_000_000_000)))
    args = parser.parse_args()

    if args.list:
        for key, fn in SCENARIOS:
            print(f"{key:6s} {fn.__name__}")
        return 0

    keyfile = os.environ.get("BQ_KEYFILE")
    if not keyfile:
        sys.exit("set BQ_KEYFILE to the service-account key path, e.g.\n"
                 "  export BQ_KEYFILE=/path/to/service-account.json\n"
                 "(the harness only passes the path through to DuckDB; it never prints "
                 "its contents)")
    if not Path(keyfile).exists():
        sys.exit(f"service-account key not found at {keyfile}: set BQ_KEYFILE (path only; "
                 f"this harness never prints its contents)")
    TMP.mkdir(parents=True, exist_ok=True)
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    client = Client(keyfile, args.billing_project, args.bucket)
    subs = {
        "__SA_PATH__": keyfile,
        "__TOKEN__": access_token(keyfile, force=True),
        "__BUCKET__": args.bucket,
        "__PREFIX__": args.prefix,
        "__BILLING__": args.billing_project,
        "__DATA_PROJECT__": args.data_project,
        "__RUN_ID__": run_id,
        "__LOCAL_DIR__": str(TMP / "b10"),
        "__PARQUET_OUT__": str(TMP / "reverse_src.parquet"),
        "__DUMP_OUT__": str(TMP / "reverse_src_dump.csv"),
        "__REVERSE_BUILD__": str(TMP / "reverse_build.sql"),
        "__URLS__": "[]",
    }
    # b26's SQL, rendered: b28 substitutes it so it can build the same DuckDB table
    build = (SQL_DIR / "b26_reverse_write_parquet.sql").read_text()
    for placeholder, value in subs.items():
        build = build.replace(placeholder, str(value))
    subs["__REVERSE_SQL__"] = build

    h = Harness(client, subs, run_id)
    wanted = set(args.only or [])
    selected = [(k, fn) for k, fn in SCENARIOS if not wanted or k in wanted]
    if wanted:
        unknown = wanted - {k for k, _ in SCENARIOS}
        if unknown:
            sys.exit(f"unknown scenario key(s): {', '.join(sorted(unknown))}")
    if args.skip_cleanup:
        selected = [(k, fn) for k, fn in selected if k != "b31"]

    started_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    for key, fn in selected:
        print(f"[{key}] running ...", flush=True)
        try:
            result = fn(h)
            metrics = result["metrics"]
            print(f"[{key}] {result['status']} wall={result['wall_s']}s "
                  f"errors_expected={metrics.get('errors_expected')} log={result['log']}",
                  flush=True)
            for line in metrics.get("error_lines", [])[:2]:
                print(f"      {str(line)[:160]}", flush=True)
        except Exception as exc:  # noqa: BLE001
            import traceback
            trace = traceback.format_exc()
            log = h.log(key, [f"{key}: CRASHED in the harness"], trace)
            h.record(key, TITLES.get(key, key), log, 0.0, "harness-error",
                     {"error_lines": [str(exc)]})
            print(f"[{key}] harness error: {exc}", flush=True)

    write_results(h, duckdb_cli(), run_id, started_at,
                  dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"))
    mismatched = [r["key"] for r in h.results
                  if (r["status"] != "ok") != bool(r["metrics"].get("errors_expected"))]
    if mismatched:
        print("scenarios that did NOT behave as expected: " + ", ".join(mismatched))
    print(f"wrote {BASE.relative_to(REPO)}/results.json and results.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
