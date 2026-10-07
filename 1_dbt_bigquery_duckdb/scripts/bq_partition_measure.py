#!/usr/bin/env python3
"""Measure what partitioning and clustering do to one table's scan cost on BigQuery.

    python3 scripts/bq_partition_measure.py measure --table PROJECT.DATASET.TABLE \\
        --label before|after --window YYYY-MM [--out-dir analyses/partitioning]
    python3 scripts/bq_partition_measure.py report --before FILE --after FILE \\
        [--out-dir analyses/partitioning]

The harness behind analyses/partitioning/README.md (`make partition-measure ARGS=...`).

`measure` reads, for one table:
  1. its metadata, from the REST `tables.get` endpoint (rows, bytes, timePartitioning,
     clustering, creation and modification time). A metadata read: not a query job, it
     bills nothing and cannot hit the ceiling;
  2. four query jobs, each submitted with `jobs.insert` and read back with `jobs.get`:
     `dry_run` (the filtered query with dryRun: free, an estimate), `full_scan`
     (SELECT *), `filtered_scan` (SELECT * over one calendar month of created_at, the
     representative query) and `filtered_count` (COUNT(*) over the same month, the
     10 MB-minimum control). Every executed job carries useQueryCache: false and
     maximumBytesBilled; a cache hit makes the run unusable (exit 1);
  3. rows per partition, from the dataset's INFORMATION_SCHEMA.PARTITIONS (one more
     query job under the same ceiling).
It prints everything as it goes and writes <out-dir>/logs/<label>.log (the same text)
and <out-dir>/results.<label>.json.

`report` reads a `before` and an `after` JSON of the same table and window, and writes
and prints <out-dir>/results.md. It writes nothing from BigQuery and costs nothing.

Cost: the three executed queries each bill at most the table's size (about 50 MB for
fct_inventory_items) and at least BigQuery's 10 MB per-query minimum; the partitions
query bills the minimum. Every job is capped by BQ_MAXIMUM_BYTES_BILLED (default
1000000000, the 1 GB profiles.yml carries); a job refused by that ceiling is recorded
as refused, with BigQuery's own message, and the run carries on.

Environment: BQ_KEYFILE (a service-account key file; required, never printed),
BQ_PROJECT (the project the jobs run and bill in; default coreychimpbot),
BQ_MAXIMUM_BYTES_BILLED (default 1000000000). The token comes from
scripts/parity.py's access_token(), the one JWT exchange in this repository.

Exit status:
  0  everything ran (measure), or the comparison was written (report);
  1  a job failed or was refused, a job reported a cache hit, or the report cannot be
     honestly produced (missing file, not a before/after pair of the same table and
     window, a cache hit in either run);
  2  could not start: no BQ_KEYFILE, an unreadable key, no token, the network.
"""
from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://bigquery.googleapis.com/bigquery/v2/projects/{project}"
REPO = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO / "analyses" / "partitioning"
MIN_BILLED = 10 * 1024 * 1024  # BigQuery's per-query minimum billed, 10 MB
QUERIES = ["dry_run", "full_scan", "filtered_scan", "filtered_count"]
SPECIAL_PARTITIONS = ("__NULL__", "__UNPARTITIONED__")
POLL_SECONDS = 600


def _access_token(key: str) -> str:
    # One implementation of the JWT exchange in this repository: parity.py's.
    spec = importlib.util.spec_from_file_location(
        "parity", Path(__file__).resolve().parent / "parity.py")
    parity = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parity)
    return parity.access_token(key)


def _call(token: str, url: str, body: dict | None = None):
    """(status, parsed JSON). HTTP errors are returned, not raised; network errors raise."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data)
    req.add_header("Authorization", "Bearer " + token)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"error": {"message": raw[:400]}}


def _ts(ms) -> str | None:
    if ms in (None, ""):
        return None
    return datetime.datetime.fromtimestamp(int(ms) / 1000, datetime.timezone.utc) \
        .strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + "Z"


def _int(v) -> int | None:
    return None if v in (None, "") else int(v)


def _fmt_bytes(n) -> str:
    if n is None:
        return "n/a"
    return f"{n:,} ({n / 1024 / 1024:.2f} MiB)"


def _window(value: str) -> tuple[str, str]:
    m = re.fullmatch(r"(\d{4})-(\d{2})", value)
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise argparse.ArgumentTypeError(f"--window must be YYYY-MM, got {value!r}")
    year, month = int(m.group(1)), int(m.group(2))
    nxt = (year + 1, 1) if month == 12 else (year, month + 1)
    return f"{year:04d}-{month:02d}-01 00:00:00", f"{nxt[0]:04d}-{nxt[1]:02d}-01 00:00:00"


def _table(value: str) -> tuple[str, str, str]:
    parts = value.split(".")
    if len(parts) != 3 or not all(parts):
        raise argparse.ArgumentTypeError(f"--table must be PROJECT.DATASET.TABLE, got {value!r}")
    return parts[0], parts[1], parts[2]


# --------------------------------------------------------------------------- measure

class Run:
    """Prints a line and keeps it for the log file."""

    def __init__(self):
        self.lines: list[str] = []

    def say(self, msg: str = "") -> None:
        print(msg, flush=True)
        self.lines.append(msg)


def _error_of(payload: dict) -> tuple[str, str]:
    """(reason, message) from an HTTP error body or a job's status.errorResult."""
    if "errorResult" in payload.get("status", {}):
        err = payload["status"]["errorResult"]
        return err.get("reason", ""), err.get("message", "")
    err = payload.get("error", {})
    reasons = ",".join(x.get("reason", "") for x in err.get("errors", []) if x.get("reason"))
    return reasons, err.get("message", "")


def _run_job(token: str, project: str, location: str, sql: str, ceiling: int,
             dry_run: bool = False) -> dict:
    """Submit one query job and read it back. Returns the recorded fields."""
    base = API.format(project=project)
    config = {"query": {"query": sql, "useLegacySql": False}}
    if dry_run:
        config["dryRun"] = True
    else:
        config["query"]["useQueryCache"] = False
        config["query"]["maximumBytesBilled"] = str(ceiling)
    body = {"jobReference": {"projectId": project, "location": location},
            "configuration": config}
    rec: dict = {"sql": sql, "dry_run": dry_run,
                 "use_query_cache": None if dry_run else False,
                 "maximum_bytes_billed": None if dry_run else ceiling}

    status, job = _call(token, f"{base}/jobs", body)
    if status != 200:
        reason, message = _error_of(job)
        rec.update(state="refused" if "bytesBilledLimitExceeded" in reason else "failed",
                   http_status=status, reason=reason, message=message)
        return rec
    ref = job.get("jobReference", {})
    rec["job_id"] = ref.get("jobId")
    rec["location"] = ref.get("location", location)

    if not dry_run:
        # jobs.get until DONE: every number below comes from the job resource.
        url = (f"{base}/jobs/{urllib.parse.quote(ref['jobId'])}"
               f"?location={urllib.parse.quote(rec['location'])}")
        deadline = time.monotonic() + POLL_SECONDS
        while job.get("status", {}).get("state") != "DONE":
            if time.monotonic() > deadline:
                rec.update(state="failed", reason="timeout",
                           message=f"job not DONE after {POLL_SECONDS} s")
                return rec
            time.sleep(1)
            status, job = _call(token, url)
            if status != 200:
                reason, message = _error_of(job)
                rec.update(state="failed", http_status=status, reason=reason, message=message)
                return rec
        rec["read_back"] = "jobs.get"
    else:
        # A dry-run job is validated and answered in the insert response; BigQuery does
        # not persist it, so there is nothing for jobs.get to read back.
        rec["read_back"] = "jobs.insert response (dry run, not persisted)"

    if "errorResult" in job.get("status", {}):
        reason, message = _error_of(job)
        rec.update(state="refused" if reason == "bytesBilledLimitExceeded" else "failed",
                   reason=reason, message=message)
        return rec

    stats = job.get("statistics", {})
    q = stats.get("query", {})
    rec.update(
        state="done",
        total_bytes_processed=_int(q.get("totalBytesProcessed")),
        total_bytes_billed=_int(q.get("totalBytesBilled")),
        cache_hit=q.get("cacheHit"),
        statement_type=q.get("statementType"),
        schema_fields=len(q.get("schema", {}).get("fields", [])) if "schema" in q else None,
        creation_time=_ts(stats.get("creationTime")),
        end_time=_ts(stats.get("endTime")),
        total_slot_ms=_int(stats.get("totalSlotMs")),
    )
    if rec["creation_time"] and rec["end_time"]:
        rec["elapsed_ms"] = int(stats["endTime"]) - int(stats["creationTime"])
    return rec


def _say_job(run: Run, name: str, rec: dict) -> None:
    run.say(f"[{name}]")
    run.say(f"  sql:                 {rec['sql']}")
    if rec["state"] != "done":
        tag = "REFUSED by maximumBytesBilled" if rec["state"] == "refused" else "FAILED"
        run.say(f"  {tag}: reason={rec.get('reason', '')}")
        run.say(f'  BigQuery said:       "{rec.get("message", "")}"')
        if rec.get("job_id"):
            run.say(f"  jobId:               {rec['job_id']}")
        return
    run.say(f"  jobId:               {rec.get('job_id') or '(none: dry run)'}  "
            f"[read back from {rec['read_back']}]")
    run.say(f"  totalBytesProcessed: {_fmt_bytes(rec['total_bytes_processed'])}")
    if not rec["dry_run"]:
        run.say(f"  totalBytesBilled:    {_fmt_bytes(rec['total_bytes_billed'])}")
        run.say(f"  cacheHit:            {str(rec['cache_hit']).lower()}")
    run.say(f"  statementType:       {rec['statement_type']}")
    run.say(f"  schema fields:       {rec['schema_fields']}")
    if not rec["dry_run"]:
        run.say(f"  creationTime:        {rec['creation_time']}")
        run.say(f"  endTime:             {rec['end_time']}  ({rec.get('elapsed_ms')} ms)")
        run.say(f"  totalSlotMs:         {rec['total_slot_ms']}")
    if rec.get("cache_hit"):
        run.say("  !!! CACHE HIT: BigQuery answered from its result cache, so this job billed "
                "nothing and measures nothing. THIS RUN IS UNUSABLE.")


def _query_rows(token: str, project: str, location: str, job_id: str) -> list[list]:
    """Every row of a finished job, via jobs.getQueryResults, values as strings."""
    base = API.format(project=project)
    rows: list[list] = []
    page = None
    while True:
        params = {"location": location, "maxResults": "10000"}
        if page:
            params["pageToken"] = page
        status, res = _call(token, f"{base}/queries/{urllib.parse.quote(job_id)}?"
                            + urllib.parse.urlencode(params))
        if status != 200:
            reason, message = _error_of(res)
            raise RuntimeError(f"getQueryResults HTTP {status} {reason}: {message}")
        rows += [[c.get("v") for c in r.get("f", [])] for r in res.get("rows", [])]
        page = res.get("pageToken")
        if not page:
            return rows


def measure(args) -> int:
    key = os.environ.get("BQ_KEYFILE")
    if not key or not Path(key).is_file():
        print("bq_partition_measure: BQ_KEYFILE is not set or is not a file; nothing was "
              "measured. Export the service-account key path and re-run.", file=sys.stderr)
        return 2
    project = os.environ.get("BQ_PROJECT", "coreychimpbot")
    try:
        ceiling = int(os.environ.get("BQ_MAXIMUM_BYTES_BILLED", "1000000000"))
    except ValueError:
        print("bq_partition_measure: BQ_MAXIMUM_BYTES_BILLED is not an integer",
              file=sys.stderr)
        return 2
    t_project, t_dataset, t_table = args.table
    fq = ".".join(args.table)
    lo, hi = args.window_bounds
    out_dir = Path(args.out_dir)

    try:
        token = _access_token(key)
    except Exception as e:  # noqa: BLE001
        print(f"bq_partition_measure: could not obtain an access token "
              f"({type(e).__name__}); nothing was measured.", file=sys.stderr)
        return 2

    run = Run()
    started = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    result: dict = {"label": args.label, "table": fq, "window": args.window,
                    "window_bounds": [lo, hi], "job_project": project,
                    "maximum_bytes_billed": ceiling, "started": started}
    run.say(f"bq_partition_measure: label {args.label}, table {fq}, window {args.window} "
            f"[{lo}, {hi})")
    run.say(f"jobs run in project {project}; maximumBytesBilled {ceiling:,}; "
            f"useQueryCache false; started {started}")
    run.say()

    try:
        # 1. tables.get ---------------------------------------------------------------
        status, meta = _call(token, f"{API.format(project=t_project)}/datasets/"
                             f"{t_dataset}/tables/{t_table}")
        if status != 200:
            reason, message = _error_of(meta)
            print(f"bq_partition_measure: tables.get {fq}: HTTP {status} {reason}: "
                  f'"{message}"; nothing was measured.', file=sys.stderr)
            return 2
        tp = meta.get("timePartitioning")
        cl = meta.get("clustering", {}).get("fields")
        location = meta.get("location", "US")
        result["metadata"] = {
            "num_rows": _int(meta.get("numRows")),
            "num_bytes": _int(meta.get("numBytes")),
            "time_partitioning": None if not tp else {
                "type": tp.get("type"), "field": tp.get("field"),
                "expiration_ms": _int(tp.get("expirationMs"))},
            "clustering_fields": cl or None,
            "creation_time": _ts(meta.get("creationTime")),
            "last_modified_time": _ts(meta.get("lastModifiedTime")),
            "location": location,
        }
        m = result["metadata"]
        run.say("[table metadata] (tables.get; a metadata read, bills nothing)")
        run.say(f"  numRows:          {m['num_rows']:,}" if m["num_rows"] is not None
                else "  numRows:          n/a")
        run.say(f"  numBytes:         {_fmt_bytes(m['num_bytes'])}")
        if tp:
            run.say(f"  timePartitioning: type={tp.get('type')} field={tp.get('field')} "
                    f"expirationMs={tp.get('expirationMs', 'none')}")
        else:
            run.say("  timePartitioning: none")
        run.say(f"  clustering:       {', '.join(cl) if cl else 'none'}")
        run.say(f"  creationTime:     {m['creation_time']}")
        run.say(f"  lastModifiedTime: {m['last_modified_time']}")
        run.say(f"  location:         {location}")
        run.say()

        # 2. the four query jobs ------------------------------------------------------
        where = (f"WHERE created_at >= TIMESTAMP '{lo}' "
                 f"AND created_at < TIMESTAMP '{hi}'")
        sqls = {
            "dry_run": f"SELECT * FROM `{fq}` {where}",
            "full_scan": f"SELECT * FROM `{fq}`",
            "filtered_scan": f"SELECT * FROM `{fq}` {where}",
            "filtered_count": f"SELECT COUNT(*) FROM `{fq}` {where}",
        }
        result["queries"] = {}
        for name in QUERIES:
            rec = _run_job(token, project, location, sqls[name], ceiling,
                           dry_run=(name == "dry_run"))
            result["queries"][name] = rec
            _say_job(run, name, rec)
            run.say()

        # 3. INFORMATION_SCHEMA.PARTITIONS --------------------------------------------
        psql = (f"SELECT partition_id, total_rows, total_logical_bytes, total_billable_bytes "
                f"FROM `{t_project}.{t_dataset}.INFORMATION_SCHEMA.PARTITIONS` "
                f"WHERE table_name = '{t_table}' ORDER BY partition_id")
        prec = _run_job(token, project, location, psql, ceiling)
        result["partitions_job"] = prec
        _say_job(run, "partitions", prec)
        if prec["state"] == "done":
            rows = _query_rows(token, project, prec["location"], prec["job_id"])
            parts = [{"partition_id": r[0], "total_rows": _int(r[1]),
                      "total_logical_bytes": _int(r[2]),
                      "total_billable_bytes": _int(r[3])} for r in rows]
            result["partitions"] = parts
            result["partition_summary"] = s = _summarise(parts, args.window)
            run.say(f"  partitions listed:   {s['count']}")
            run.say(f"  first partition_id:  {s['first'] or 'none'}")
            run.say(f"  last partition_id:   {s['last'] or 'none'}")
            for special in SPECIAL_PARTITIONS:
                if special in s["special_rows"]:
                    run.say(f"  {special} rows: {s['special_rows'][special]:,}")
            if s["null_id_rows"] is not None:
                run.say(f"  partition_id NULL (whole unpartitioned table): "
                        f"{s['null_id_rows']:,} rows")
            run.say(f"  window {args.window}:      {s['window_partitions']} partition(s), "
                    f"{s['window_rows']:,} rows")
            run.say(f"  rows over real partitions: {s['real_rows']:,} "
                    f"in {s['real_partitions']} partition(s)")
        run.say()
    except (urllib.error.URLError, OSError, ValueError, RuntimeError) as e:
        print(f"bq_partition_measure: network or API failure mid-run: {type(e).__name__}: {e}. "
              "The run is incomplete; no results file was written.", file=sys.stderr)
        return 2

    jobs = [*result["queries"].items(), ("partitions", prec)]
    refused = [n for n, r in jobs if r["state"] == "refused"]
    failed = [n for n, r in jobs if r["state"] == "failed"]
    cached = [n for n, r in jobs if r.get("cache_hit")]
    result["refused"], result["failed"], result["cache_hits"] = refused, failed, cached
    result["usable"] = not (refused or failed or cached)

    if cached:
        run.say(f"UNUSABLE: cache hit on {', '.join(cached)}. A cached job bills 0 and would "
                "hide the change; this run must not be reported.")
    if refused:
        run.say(f"REFUSED by the {ceiling:,}-byte ceiling: {', '.join(refused)} "
                "(recorded as results, the ceiling was not raised)")
    if failed:
        run.say(f"FAILED: {', '.join(failed)}")
    if result["usable"]:
        run.say(f"ok: {args.label} measured, every executed job reported cacheHit false")

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "logs").mkdir(exist_ok=True)
    log = out_dir / "logs" / f"{args.label}.log"
    js = out_dir / f"results.{args.label}.json"
    run.say(f"wrote {log} and {js}")
    log.write_text("\n".join(run.lines) + "\n")
    js.write_text(json.dumps(result, indent=2) + "\n")
    return 0 if result["usable"] else 1


def _summarise(parts: list[dict], window: str) -> dict:
    prefix = window.replace("-", "")  # day partition ids are YYYYMMDD
    real = [p for p in parts
            if p["partition_id"] is not None and p["partition_id"] not in SPECIAL_PARTITIONS]
    in_window = [p for p in real if p["partition_id"].startswith(prefix)]
    null_id = [p for p in parts if p["partition_id"] is None]
    ids = [p["partition_id"] for p in parts if p["partition_id"] is not None]
    return {
        "count": len(parts),
        "first": ids[0] if ids else None,
        "last": ids[-1] if ids else None,
        "special_rows": {p["partition_id"]: p["total_rows"] or 0 for p in parts
                         if p["partition_id"] in SPECIAL_PARTITIONS},
        "null_id_rows": sum(p["total_rows"] or 0 for p in null_id) if null_id else None,
        "window_partitions": len(in_window),
        "window_rows": sum(p["total_rows"] or 0 for p in in_window),
        "real_partitions": len(real),
        "real_rows": sum(p["total_rows"] or 0 for p in real),
    }


# ---------------------------------------------------------------------------- report

def _load(path: str, label: str) -> dict:
    p = Path(path)
    if not p.is_file():
        raise ValueError(f"--{label} {path}: no such file (run `measure --label {label}` first)")
    try:
        data = json.loads(p.read_text())
    except ValueError as e:
        raise ValueError(f"--{label} {path}: not JSON ({e})")
    if data.get("label") != label:
        raise ValueError(f"--{label} {path} is the {data.get('label')!r} run, not the "
                         f"{label!r} run")
    if data.get("cache_hits"):
        raise ValueError(f"--{label} {path} recorded a cache hit on "
                         f"{', '.join(data['cache_hits'])}: that run measures nothing")
    if "queries" not in data:
        raise ValueError(f"--{label} {path} has no query results")
    return data


def _delta(b, a) -> tuple[str, str]:
    if b is None or a is None:
        return "n/a", "n/a"
    d = a - b
    pct = "n/a" if b == 0 else f"{d / b * 100:+.1f}%"
    return f"{d:+,}", pct


def _cell(rec: dict, field: str) -> str:
    if rec["state"] != "done":
        return rec["state"]
    v = rec.get(field)
    return "n/a" if v is None else f"{v:,}"


def _reading(name: str, b: dict, a: dict, before: dict, after: dict) -> str:
    if b["state"] != "done" or a["state"] != "done":
        return (f"not comparable: before {b['state']}, after {a['state']} "
                f"({b.get('reason') or a.get('reason')})")
    bp, ap = b["total_bytes_processed"], a["total_bytes_processed"]
    if name == "dry_run":
        ex = after["queries"]["filtered_scan"]
        tail = ""
        if ex["state"] == "done":
            tail = (f"; the executed after job processed {ex['total_bytes_processed']:,}, "
                    + ("the same as the estimate" if ex["total_bytes_processed"] == ap
                       else f"{_delta(ap, ex['total_bytes_processed'])[1]} against the estimate"))
        return f"the estimate moved from {bp:,} to {ap:,} bytes{tail}."
    bb, ab = b["total_bytes_billed"], a["total_bytes_billed"]
    if name == "full_scan":
        return (f"the whole table, both times: processed {bp:,} -> {ap:,} bytes "
                f"({_delta(bp, ap)[1]}); the denominator for filtered_scan.")
    if name == "filtered_scan":
        fb = before["queries"]["full_scan"]
        fa = after["queries"]["full_scan"]
        share = []
        for leg, full, x in (("before", fb, bp), ("after", fa, ap)):
            if full["state"] == "done" and full["total_bytes_processed"]:
                share.append(f"{leg} {x / full['total_bytes_processed'] * 100:.1f}%")
        return (f"one month of created_at read {', '.join(share)} of the full scan; "
                f"billed {bb:,} -> {ab:,} ({_delta(bb, ab)[1]}).")
    floored = [leg for leg, x in (("before", bb), ("after", ab)) if x == MIN_BILLED]
    note = (f"billed at the 10 MB minimum ({MIN_BILLED:,}) in {' and '.join(floored)}"
            if floored else "neither leg billed at the 10 MB minimum")
    return f"processed {bp:,} -> {ap:,} bytes; {note}."


def report(args) -> int:
    try:
        before = _load(args.before, "before")
        after = _load(args.after, "after")
    except ValueError as e:
        print(f"bq_partition_measure report: {e}. No report written.", file=sys.stderr)
        return 1
    if before["table"] != after["table"]:
        print(f"bq_partition_measure report: before measured {before['table']}, after measured "
              f"{after['table']}: a comparison across two tables would be a fabricated "
              "result. No report written.", file=sys.stderr)
        return 1
    if before["window"] != after["window"]:
        print(f"bq_partition_measure report: before used window {before['window']}, after "
              f"{after['window']}: the filtered queries are not the same query. "
              "No report written.", file=sys.stderr)
        return 1

    mb, ma = before["metadata"], after["metadata"]

    def tp(m):
        t = m["time_partitioning"]
        return "none" if not t else f"{t['type']} on `{t['field']}`" + (
            f", expires {t['expiration_ms']} ms" if t.get("expiration_ms") else "")

    lines = [
        f"# Partitioning measured: `{before['table']}`",
        "",
        "Generated by `scripts/bq_partition_measure.py report` from "
        f"`{Path(args.before).name}` (started {before['started']}) and "
        f"`{Path(args.after).name}` (started {after['started']}). Every byte figure is "
        "BigQuery's own, read from the jobs API; every executed job ran with "
        f"`useQueryCache: false` and `maximumBytesBilled` {after['maximum_bytes_billed']:,}.",
        "",
        f"Window: `{before['window']}`, i.e. `created_at >= TIMESTAMP '{before['window_bounds'][0]}'"
        f" AND created_at < TIMESTAMP '{before['window_bounds'][1]}'`.",
        "",
        "## Table metadata (`tables.get`)",
        "",
        "| | before | after |",
        "|---|---|---|",
        f"| numRows | {mb['num_rows']:,} | {ma['num_rows']:,} |",
        f"| numBytes | {mb['num_bytes']:,} | {ma['num_bytes']:,} |",
        f"| timePartitioning | {tp(mb)} | {tp(ma)} |",
        f"| clustering | {', '.join(mb['clustering_fields'] or []) or 'none'} | "
        f"{', '.join(ma['clustering_fields'] or []) or 'none'} |",
        f"| creationTime | {mb['creation_time']} | {ma['creation_time']} |",
        f"| lastModifiedTime | {mb['last_modified_time']} | {ma['last_modified_time']} |",
        "",
    ]
    for name in QUERIES:
        b, a = before["queries"][name], after["queries"][name]
        lines += [f"## `{name}`", "", "```sql", a["sql"], "```", "",
                  "| | before | after | delta | delta % |", "|---|---|---|---|---|"]
        fields = [("bytes processed", "total_bytes_processed")]
        if name != "dry_run":
            fields.append(("bytes billed", "total_bytes_billed"))
        for title, field in fields:
            d, pct = ((_delta(b.get(field), a.get(field)))
                      if b["state"] == a["state"] == "done" else ("n/a", "n/a"))
            lines.append(f"| {title} | {_cell(b, field)} | {_cell(a, field)} | {d} | {pct} |")
        if name != "dry_run":
            lines.append(f"| cacheHit | {str(b.get('cache_hit')).lower()} | "
                         f"{str(a.get('cache_hit')).lower()} | | |")
            lines.append(f"| jobId | `{b.get('job_id')}` | `{a.get('job_id')}` | | |")
        lines += ["", f"Reading: {_reading(name, b, a, before, after)}", ""]

    lines += ["## Partitions (`INFORMATION_SCHEMA.PARTITIONS`)", "",
              "| | before | after |", "|---|---|---|"]
    sb, sa = before.get("partition_summary"), after.get("partition_summary")
    if sb and sa:
        def special(s, k):
            v = s["special_rows"].get(k)
            return "absent" if v is None else f"{v:,} rows"

        def nullid(s):
            return "absent" if s["null_id_rows"] is None else f"{s['null_id_rows']:,} rows"
        lines += [
            f"| partitions listed | {sb['count']} | {sa['count']} |",
            f"| first partition_id | {sb['first'] or 'none'} | {sa['first'] or 'none'} |",
            f"| last partition_id | {sb['last'] or 'none'} | {sa['last'] or 'none'} |",
            f"| `__UNPARTITIONED__` | {special(sb, '__UNPARTITIONED__')} | "
            f"{special(sa, '__UNPARTITIONED__')} |",
            f"| `__NULL__` | {special(sb, '__NULL__')} | {special(sa, '__NULL__')} |",
            f"| partition_id NULL (unpartitioned table) | {nullid(sb)} | {nullid(sa)} |",
            f"| partitions in {before['window']} | {sb['window_partitions']} | "
            f"{sa['window_partitions']} |",
            f"| rows in {before['window']} | {sb['window_rows']:,} | {sa['window_rows']:,} |",
            f"| rows over real partitions | {sb['real_rows']:,} | {sa['real_rows']:,} |",
            "",
        ]
    else:
        lines += ["| partitions | " + ("listed" if sb else before["partitions_job"]["state"])
                  + " | " + ("listed" if sa else after["partitions_job"]["state"]) + " |", ""]

    incomplete = sorted(set(before.get("refused", []) + before.get("failed", [])
                            + after.get("refused", []) + after.get("failed", [])))
    if incomplete:
        lines += [f"**Incomplete:** {', '.join(incomplete)} did not run to completion in at "
                  "least one leg (refused or failed); those rows are not compared.", ""]

    text = "\n".join(lines)
    out = Path(args.out_dir) / "results.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text)
    print(text)
    print(f"wrote {out}")
    return 1 if incomplete else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        epilog="See analyses/partitioning/README.md for the full protocol.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("measure", help="measure one leg (before or after) of one table; "
                       "runs real BigQuery jobs and costs bytes")
    m.add_argument("--table", required=True, type=_table, metavar="PROJECT.DATASET.TABLE")
    m.add_argument("--label", required=True, choices=["before", "after"])
    m.add_argument("--window", required=True, metavar="YYYY-MM",
                   help="the calendar month of created_at the filtered queries read")
    m.add_argument("--out-dir", default=str(DEFAULT_OUT),
                   help="where logs/<label>.log and results.<label>.json go "
                   "(default analyses/partitioning)")

    r = sub.add_parser("report", help="compare a before and an after run of the same table; "
                       "reads two JSON files, runs nothing")
    r.add_argument("--before", required=True, metavar="FILE")
    r.add_argument("--after", required=True, metavar="FILE")
    r.add_argument("--out-dir", default=str(DEFAULT_OUT),
                   help="where results.md goes (default analyses/partitioning)")

    args = ap.parse_args(argv)
    if args.cmd == "measure":
        try:
            args.window_bounds = _window(args.window)
        except argparse.ArgumentTypeError as e:
            m.error(str(e))
        return measure(args)
    return report(args)


if __name__ == "__main__":
    sys.exit(main())
