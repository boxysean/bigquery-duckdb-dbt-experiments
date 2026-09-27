#!/usr/bin/env python3
"""Transport A: DuckDB reading BigQuery through the community `bigquery` extension.

This is the harness behind analyses/transport_a/README.md. It runs one DuckDB CLI
process per scenario in analyses/transport_a/sql/, and for each one records

  * wall time (measured here) and peak RSS (measured by /usr/bin/time -v),
  * the process exit status and the full stdout+stderr (analyses/transport_a/logs/),
  * the evidence the card asks for: the projection and row restriction lines the
    extension hands to BigQuery (bq_debug_show_queries), and any remote query jobs
    it submitted,

into analyses/transport_a/results.json and a generated results.md table.

Nothing here decides pass/fail by itself: a scenario that fails is recorded with
its error text, because the failure modes are part of the deliverable.

Usage
-----
    BQ_KEYFILE=/path/to/service-account.json python3 scripts/transport_a_measure.py
    python3 scripts/transport_a_measure.py --only t05 t06 t13     # a subset
    python3 scripts/transport_a_measure.py --list

The service-account key is never printed: only its path is passed to DuckDB, via
the __SA_PATH__ placeholder substituted into each .sql file at run time.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SQL_DIR = REPO / "analyses" / "transport_a" / "sql"
OUT_DIR = REPO / "analyses" / "transport_a"
LOG_DIR = OUT_DIR / "logs"
TMP_DIR = Path(os.environ.get("TRANSPORT_A_TMP", Path(tempfile.gettempdir()) / "transport_a"))

DEFAULT_BILLING = "coreychimpbot"
DEFAULT_DATA_PROJECT = "bigquery-public-data"
TIME_BIN = "/usr/bin/time"

# Every scenario file, in the order it should run. t12b cleans up after t12 and is
# always run, even when t12 itself fails.
SCENARIOS = [
    {"key": "t01", "file": "t01_install_plain_core.sql",
     "title": "INSTALL bigquery (core repository)", "fresh_home": True, "expect_failure": True},
    {"key": "t02", "file": "t02_install_from_community.sql",
     "title": "INSTALL bigquery FROM community", "fresh_home": True, "expect_failure": False},
    {"key": "t03", "file": "t03_secret_scope_wrong.sql",
     "title": "secret SCOPE vs project (the trap)", "fresh_home": False, "expect_failure": True},
    {"key": "t04", "file": "t04_secret_scope_right.sql",
     "title": "secret SCOPE follows the data", "fresh_home": False, "expect_failure": False},
    {"key": "t05", "file": "t05_pushdown_filter.sql",
     "title": "WHERE predicate pushdown", "fresh_home": False, "expect_failure": False},
    {"key": "t06", "file": "t06_pushdown_projection.sql",
     "title": "column pruning", "fresh_home": False, "expect_failure": False},
    {"key": "t07", "file": "t07_cost_guard.sql",
     "title": "dry_run vs billed bytes", "fresh_home": False, "expect_failure": False},
    {"key": "t07b", "file": "t07b_dry_run_vs_billed.sql",
     "title": "one shape: predicted vs billed bytes", "fresh_home": False, "expect_failure": False},
    {"key": "t07c", "file": "t07c_count_star_is_free.sql",
     "title": "COUNT(*) is metadata, COUNT(col) is a scan", "fresh_home": False, "expect_failure": False},
    {"key": "t08", "file": "t08_aggregate_pushdown_off.sql",
     "title": "aggregate pushdown OFF (default)", "fresh_home": False, "expect_failure": False},
    {"key": "t09", "file": "t09_aggregate_pushdown_on.sql",
     "title": "aggregate pushdown ON", "fresh_home": False, "expect_failure": False},
    {"key": "t10", "file": "t10_attach_dataset_readonly.sql",
     "title": "ATTACH one dataset, READ_ONLY", "fresh_home": False, "expect_failure": False},
    {"key": "t11", "file": "t11_attach_project_readonly.sql",
     "title": "ATTACH a whole project, READ_ONLY", "fresh_home": False, "expect_failure": True},
    {"key": "t12", "file": "t12_attach_writable.sql",
     "title": "READ_ONLY guard vs writable catalog", "fresh_home": False, "expect_failure": True},
    {"key": "t12b", "file": "t12b_attach_writable_cleanup.sql",
     "title": "writable catalog: insert, read back, drop", "fresh_home": False, "expect_failure": False},
    {"key": "t12c", "file": "t12c_writable_leftover_check.sql",
     "title": "verify no probe table remains", "fresh_home": False, "expect_failure": False},
    {"key": "t13", "file": "t13_parallelism.sql",
     "title": "read parallelism", "fresh_home": False, "expect_failure": False},
    {"key": "t14", "file": "t14_materialize_full_table.sql",
     "title": "materialize a whole table (Storage Read API)", "fresh_home": False, "expect_failure": False},
    {"key": "t15", "file": "t15_types_storage_api.sql",
     "title": "type fidelity, Storage path", "fresh_home": False, "expect_failure": False},
    {"key": "t16", "file": "t16_types_rest_api.sql",
     "title": "type fidelity, REST path", "fresh_home": False, "expect_failure": False},
    {"key": "t17", "file": "t17_rest_projection_cast_bug.sql",
     "title": "REST decoder failure mode", "fresh_home": False, "expect_failure": True},
    {"key": "t18", "file": "t18_dry_run_projection_error.sql",
     "title": "dry-run result projection INTERNAL error", "fresh_home": False, "expect_failure": True},
]

SELECTED_FIELDS_RE = re.compile(r"^BigQuery selected fields: (.*)$", re.M)
ROW_RESTRICTION_RE = re.compile(r"^BigQuery row restrictions: (.*)$", re.M)
REMOTE_QUERY_RE = re.compile(r"^query: (.*)$", re.M)


def duckdb_cli() -> str:
    for candidate in (os.environ.get("DUCKDB_CLI"), shutil.which("duckdb"),
                      str(Path.home() / ".local" / "bin" / "duckdb")):
        if candidate and Path(candidate).exists():
            return candidate
    sys.exit("no duckdb CLI found: set DUCKDB_CLI or put duckdb on PATH")


def substitution_env() -> dict:
    keyfile = os.environ.get("BQ_KEYFILE")
    if not keyfile:
        sys.exit(
            "set BQ_KEYFILE to the service-account key path, e.g.\n"
            "  export BQ_KEYFILE=/path/to/service-account.json\n"
            "The dev box's key path is in the team runbook; this harness never reads\n"
            "or prints the file's contents, only hands the path to DuckDB."
        )
    if not Path(keyfile).exists():
        sys.exit(f"BQ_KEYFILE points at {keyfile}, which does not exist or is not readable")
    return {
        "__SA_PATH__": keyfile,
        "__BILLING__": os.environ.get("BQ_BILLING_PROJECT", DEFAULT_BILLING),
        "__DATA_PROJECT__": os.environ.get("BQ_DATA_PROJECT", DEFAULT_DATA_PROJECT),
        "__TMP__": str(TMP_DIR),
        # A unique marker per run: dropped into the GoogleSQL text of the
        # dry-run/billing scenarios so BigQuery's query-results cache cannot answer
        # them, which is what makes "predicted bytes" and "bytes actually scanned"
        # comparable in one log.
        "__RUN_ID__": dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
    }


def render(sql: str, subs: dict) -> str:
    for placeholder, value in subs.items():
        sql = sql.replace(placeholder, value)
    return sql


def run_scenario(cli: str, key: str, sql_file: str, subs: dict, fresh_home: bool) -> dict:
    sql = render((SQL_DIR / sql_file).read_text(), subs)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{key}.log"
    time_path = TMP_DIR / f"{key}.time"

    env = dict(os.environ)
    if fresh_home:
        # An empty HOME means an empty extension cache, so INSTALL really hits the
        # network and cannot be answered from ~/.duckdb/extensions.
        home = TMP_DIR / f"{key}_home"
        if home.exists():
            shutil.rmtree(home)
        home.mkdir(parents=True)
        env["HOME"] = str(home)

    cmd = [TIME_BIN, "-v", "-o", str(time_path), cli, "-init", "/dev/null", ":memory:"]
    started = time.monotonic()
    proc = subprocess.run(cmd, input=sql, text=True, capture_output=True, env=env)
    wall = time.monotonic() - started

    peak_rss_kb = None
    if time_path.exists():
        match = re.search(r"Maximum resident set size \(kbytes\): (\d+)", time_path.read_text())
        if match:
            peak_rss_kb = int(match.group(1))

    combined = proc.stdout + proc.stderr
    # The logs are committed: keep the SQL as run, but never the box's key path.
    key_path = subs.get("__SA_PATH__")
    redact = (lambda text: text.replace(key_path, "__SA_PATH__")) if key_path else (lambda text: text)
    log_path.write_text(
        f"# {key}: {sql_file}\n"
        f"# wall {wall:.2f}s  exit {proc.returncode}  peak RSS {peak_rss_kb} kB\n"
        f"# command: {' '.join(cmd)} <<'SQL'\n"
        f"# (SQL as run, after placeholder substitution; __SA_PATH__ stands for the\n"
        f"#  service-account key path, which is never written to this log)\n\n"
        f"{redact(sql)}\n# ---- output ----\n{redact(combined)}\n"
    )

    return {
        "key": key,
        "sql_file": sql_file,
        "sql_path": str((SQL_DIR / sql_file).relative_to(REPO)),
        "wall_s": round(wall, 2),
        "peak_rss_kb": peak_rss_kb,
        "exit_code": proc.returncode,
        "status": "ok" if proc.returncode == 0 else "error",
        "selected_fields": SELECTED_FIELDS_RE.findall(combined),
        "row_restrictions": ROW_RESTRICTION_RE.findall(combined),
        "remote_queries": REMOTE_QUERY_RE.findall(combined),
        "error_lines": [
            line for line in combined.splitlines()
            if re.match(r"^(Binder|Parser|Invalid|Permission|Catalog|IO|Conversion|Transaction|INTERNAL|FATAL) "
                        r"(Error|Input Error)", line)
        ],
        "log": str(log_path.relative_to(REPO)),
    }


def write_results(results: list[dict], subs: dict, cli: str) -> None:
    version = subprocess.run([cli, "--version"], capture_output=True, text=True).stdout.strip()
    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "duckdb_cli": cli,
        "duckdb_version": version,
        "billing_project": subs["__BILLING__"],
        "data_project": subs["__DATA_PROJECT__"],
        "host_cpus": os.cpu_count(),
        "scenarios": results,
    }
    (OUT_DIR / "results.json").write_text(json.dumps(payload, indent=2) + "\n")

    lines = [
        "# Transport A measurements (generated)",
        "",
        f"Generated by `scripts/transport_a_measure.py` at {payload['generated_at']} with "
        f"`{version}`.",
        f"Billing project `{payload['billing_project']}`, data in `{payload['data_project']}`, "
        f"{payload['host_cpus']} CPUs on the box.",
        "Wall time is measured by the harness around the DuckDB CLI process; peak RSS is "
        "`/usr/bin/time -v` for that process. Logs: `analyses/transport_a/logs/`.",
        "",
        "| # | scenario | wall s | peak RSS MiB | exit | pushdown: selected fields | pushdown: row restriction | remote query job |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        fields = " / ".join(r["selected_fields"]) or "—"
        restr = " / ".join(r["row_restrictions"]) or "—"
        remote = "yes" if r["remote_queries"] else "no"
        rss = f"{r['peak_rss_kb'] / 1024:.0f}" if r["peak_rss_kb"] else "—"
        lines.append(
            f"| {r['key']} | {r['sql_file']} | {r['wall_s']:.2f} | {rss} | {r['exit_code']} | "
            f"{fields} | {restr} | {remote} |"
        )
    lines.append("")
    (OUT_DIR / "results.md").write_text("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="*", metavar="KEY",
                        help="run only these scenario keys (e.g. t05 t13)")
    parser.add_argument("--list", action="store_true", help="list scenarios and exit")
    args = parser.parse_args()

    if args.list:
        for scenario in SCENARIOS:
            flag = "   [errors expected]" if scenario["expect_failure"] else ""
            print(f"{scenario['key']:5s} {scenario['file']:44s} {scenario['title']}{flag}")
        return 0

    scenarios = SCENARIOS
    if args.only:
        wanted = set(args.only)
        scenarios = [s for s in SCENARIOS if s["key"] in wanted]
        missing = wanted - {s["key"] for s in scenarios}
        if missing:
            sys.exit(f"unknown scenario key(s): {', '.join(sorted(missing))}")

    cli = duckdb_cli()
    subs = substitution_env()
    results = []

    for scenario in scenarios:
        key, sql_file = scenario["key"], scenario["file"]
        print(f"[{key}] {scenario['title']} ...", flush=True)
        result = run_scenario(cli, key, sql_file, subs, scenario["fresh_home"])
        result["title"] = scenario["title"]
        result["errors_expected"] = scenario["expect_failure"]
        results.append(result)
        print(f"[{key}] exit={result['exit_code']} wall={result['wall_s']}s "
              f"rss={result['peak_rss_kb']}kB log={result['log']}", flush=True)
        for line in result["error_lines"][:2]:
            print(f"      {line[:160]}", flush=True)

    write_results(results, subs, cli)
    print(f"\nwrote {(OUT_DIR / 'results.json').relative_to(REPO)} and "
          f"{(OUT_DIR / 'results.md').relative_to(REPO)}")
    expected_mismatch = [
        r["key"] for r in results
        if (r["exit_code"] != 0) != bool(r["errors_expected"])
    ]
    if expected_mismatch:
        print("scenarios that did NOT behave as the card predicts: "
              + ", ".join(expected_mismatch))
    return 0


if __name__ == "__main__":
    sys.exit(main())
