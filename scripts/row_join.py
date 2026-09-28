#!/usr/bin/env python3
"""Row-by-row join of a matched pair of value-parity legs, every money column (SPEC-rows.md).

    BQ_KEYFILE=... DBT_ENV=rows python3 scripts/row_join.py      # make row-join DBT_ENV=rows

The pair is the one `make value-parity` last built over ONE load of the source:

  L2  dev.duckdb schema `main`: the DuckDB leg, money_type() = decimal(18,2)
  L9  the same DuckDB build with money_type() = decimal(38,9): a scratch copy of the
      tracked tree whose only difference is default__money_type(), built into schema
      `money9` of a copy of dev.duckdb under target/row_join/ (the repository is never
      edited). Reused when target/row_join/dev.duckdb still holds the same source rows.
  BQ  <project>.experiments_<DBT_ENV> (parity.SCHEMA), pulled into schema `bq_leg` of that
      copy: bigquery_scan (Storage API) for tables, bigquery_query for views (the Storage
      API refuses views), each view query dry-run first against parity.py's MAX_BYTES.

Money columns: every DECIMAL(18,2) column of L2 (money_type(); L9 must show DECIMAL(38,9)
for each) plus mart_product_performance.gross_margin_rate (float_type(), derived from
money). Key: the first, sorted, `unique` test column in target/manifest.json; every other
unique column must agree on every joined row.

GATES (a failure stops the run: exit 2 before the join, exit 1 after it)
  source   the seven thelook_ecommerce tables in dev.duckdb have BigQuery's current row
           count (tables.get), and the money source columns hash the same on both sides
           (parity.metrics_sql, float rule) - the BigQuery views read the public data live
  rows     per model, L2's row count = the BigQuery relation's (REST, parity.py's own
           BigQueryLeg.query + metrics_sql) = the fresh run's recorded row count
  transfer the extension-read copy bq_leg.<model>, measured in DuckDB with metrics_sql,
           equals the REST measurement of the same relation on every pulled column; the
           REST measurement in turn reproduces every value the fresh run recorded
Reported, never a stop: the same recomputation against the of-record run
(analyses/value_parity/results.json, 2026-09-27), whose source has since moved.

Every compared row of every money column lands in exactly one of:

  identical  BQ = L2
  A          BQ != L2, round(BQ, 2) = L2       (same cents, different declared scale)
  B          round(BQ, 2) != L2, L9 = BQ exactly (the declared scale, propagated)
  C          round(BQ, 2) != L2, L9 != BQ        (unexplained)

and every C column gets a verdict (see c_analysis): *emulation imperfect* or *genuinely
different*. The float column uses the harness's float rule, round(x * 1e6) as an integer.

Writes analyses/value_parity/rows.{md,json} and analyses/value_parity/logs/rows/. Never
writes results.*, the fresh/ evidence, the existing logs, or outside target/row_join/.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("parity", REPO / "scripts" / "parity.py")
parity = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(parity)

PROJECT = "coreychimpbot"
RELATION = f"{PROJECT}.{parity.SCHEMA}"
VP = REPO / "analyses" / "value_parity"
OF_RECORD = VP / "results.json"
FRESH = VP / "fresh" / "results.json"
LOADER_OF_RECORD = VP / "logs" / "loader.log"
LOADER_FRESH = VP / "logs" / "row_join_loader.log"
LOGS = VP / "logs" / "rows"
WORK = REPO / "target" / "row_join"
TYPES = Path("macros") / "polyglot" / "types.sql"
SOURCE_TABLES = ["distribution_centers", "products", "users", "inventory_items", "orders",
                 "order_items", "events"]
SOURCE_MONEY = {"products": ["id", "cost", "retail_price"],
                "inventory_items": ["id", "cost", "product_retail_price"],
                "order_items": ["id", "sale_price"]}
FLOAT_COLS = {("mart_product_performance", "gross_margin_rate")}
EXAMPLES = 5

# Money columns that are a direct cast of one source FLOAT64 (no arithmetic on the way):
# (model, column) -> (source table, source column, source key, model column holding it).
# Verified on every run: cast(source as decimal(18,2)) equals L2 on every row.
LINEAGE = {}
for _m, _c, _src in (
        ("stg_thelook__products", "cost", "cost"),
        ("stg_thelook__products", "retail_price", "retail_price"),
        ("dim_products", "unit_cost", "cost"),
        ("dim_products", "retail_price", "retail_price"),
        ("mart_product_performance", "unit_cost", "cost"),
        ("mart_product_performance", "retail_price", "retail_price")):
    LINEAGE[(_m, _c)] = ("products", _src, "id", "product_id")
for _m, _c, _src in (
        ("stg_thelook__inventory_items", "cost", "cost"),
        ("stg_thelook__inventory_items", "product_retail_price", "product_retail_price"),
        ("int_inventory_items__enriched", "unit_cost", "cost"),
        ("int_inventory_items__enriched", "product_retail_price", "product_retail_price"),
        ("fct_inventory_items", "unit_cost", "cost"),
        ("fct_inventory_items", "product_retail_price", "product_retail_price")):
    LINEAGE[(_m, _c)] = ("inventory_items", _src, "id", "inventory_item_id")
for _m in ("stg_thelook__order_items", "int_order_items__enriched", "fct_order_items"):
    LINEAGE[(_m, "sale_price")] = ("order_items", "sale_price", "id", "order_item_id")
for _m in ("int_order_items__enriched", "fct_order_items"):
    LINEAGE[(_m, "product_cost")] = ("inventory_items", "cost", "id", "inventory_item_id")
LINEAGE[("fct_order_items", "product_retail_price")] = (
    "products", "retail_price", "id", "product_id")

# Money columns computed as round(numerator / integer, 2) in the model itself: where L9 is
# not BigQuery on such a row, the division is recomputed both ways (see division_rows).
DIVISIONS = {
    ("mart_customer_summary", "average_order_value"): ("lifetime_gross_revenue", "lifetime_orders"),
    ("mart_daily_revenue", "average_order_value"): ("gross_revenue", "order_count"),
}

BASE_CONTROL = [("products", "cost"), ("products", "retail_price"),
                ("order_items", "sale_price"), ("inventory_items", "cost"),
                ("inventory_items", "product_retail_price")]

_log_lines: list[str] = []
KEY = ""
_KEYS: dict = {}


def log(msg: str = "") -> None:
    print(msg, flush=True)
    _log_lines.append(msg)


def redact(text: str) -> str:
    if KEY:
        text = text.replace(KEY, "$BQ_KEYFILE")
    return text.replace(str(REPO) + "/", "").replace(str(REPO), ".")


def write_log(name: str, text: str) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    (LOGS / name).write_text(redact(text))


def q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


class GateFailure(Exception):
    pass


# ---------------------------------------------------------------- DuckDB CLI
def duck_cli() -> str:
    return (os.environ.get("DUCKDB_BIN") or shutil.which("duckdb")
            or str(REPO / ".venv" / "bin" / "duckdb"))


def ddb(db: Path, sql: str, bq: bool = False, readonly: bool = False):
    """Run a script in the DuckDB CLI; return the rows of the LAST result set."""
    pre = ""
    if bq:
        pre = ("LOAD bigquery;\n"
               f"CREATE TEMPORARY SECRET rj_bq (TYPE bigquery, SCOPE 'bq://{PROJECT}',"
               f" SERVICE_ACCOUNT_PATH '{KEY}');\n")
    cmd = [duck_cli(), "-bail", "-json", "-init", "/dev/null"]
    if readonly:
        cmd.append("-readonly")
    cmd.append(str(db))
    out = subprocess.run(cmd, input=pre + sql, capture_output=True, text=True, timeout=3600)
    if out.returncode != 0:
        raise RuntimeError(redact(out.stderr.strip() or out.stdout.strip()))
    dec, text, pos, last = json.JSONDecoder(), out.stdout, 0, []
    while True:
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos >= len(text):
            return last
        last, pos = dec.raw_decode(text, pos)


def duck_metrics(db: Path, source: str, measured, readonly=False) -> dict:
    pairs = [(n, k) for n, k, _ in measured]
    row = ddb(db, parity.metrics_sql(parity.Engine("duckdb"), source, pairs), readonly=readonly)
    return parity._normalise(row[0], measured)


# ------------------------------------------------------------- BigQuery REST
def bq_api(bq, path: str):
    req = urllib.request.Request(
        f"https://bigquery.googleapis.com/bigquery/v2/projects/{path}")
    req.add_header("Authorization", "Bearer " + bq.token)
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def bq_dry_run(bq, sql: str) -> int:
    data = json.dumps({"query": sql, "useLegacySql": False, "dryRun": True,
                       "maximumBytesBilled": str(parity.MAX_BYTES)}).encode()
    req = urllib.request.Request(parity.BQ_API.format(project=PROJECT), data=data)
    req.add_header("Authorization", "Bearer " + bq.token)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return int(json.loads(resp.read().decode()).get("totalBytesProcessed", 0))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"BigQuery dry run HTTP {e.code}: {e.read().decode()[:600]}")


def bq_metrics(bq, source: str, measured) -> dict:
    _, rows = bq.query(parity.metrics_sql(bq.engine, source, [(n, k) for n, k, _ in measured]))
    return parity._normalise(rows[0], measured)


# ------------------------------------------------------------------ inputs
def manifest_keys() -> dict:
    """{model: sorted list of columns carrying a `unique` test}."""
    path = REPO / "target" / "manifest.json"
    if not path.exists():
        sys.exit(f"{path.relative_to(REPO)} is missing: run a dbt build/parse first")
    keys: dict[str, set] = {}
    for node in json.loads(path.read_text())["nodes"].values():
        meta = node.get("test_metadata") or {}
        if node.get("resource_type") == "test" and meta.get("name") == "unique":
            model = (node.get("attached_node") or "").split(".")[-1]
            col = (meta.get("kwargs") or {}).get("column_name") or node.get("column_name")
            if model and col:
                keys.setdefault(model, set()).add(col)
    return {m: sorted(c) for m, c in keys.items()}


def recorded(path: Path) -> dict:
    """{'relation', 'rows': {model: {leg: n}}, 'values': {model: {col: {check: {leg: v}}}},
    'not_measured': {model: error}} from a parity.py results.json."""
    r = json.loads(path.read_text())
    out = {"relation": r["bq_relation"], "generated_at": r["generated_at"], "rows": {},
           "values": {}, "not_measured": {}}
    for m in r["models"]:
        n = m.get("row_count") or {}
        # a not_measured model records only its DuckDB count, as a bare integer
        out["rows"][m["model"]] = n if isinstance(n, dict) else {"duckdb": n}
        if m.get("verdict") == "not_measured":
            out["not_measured"][m["model"]] = m.get("error")
        for d in m.get("differences") or []:
            if d.get("column"):
                out["values"].setdefault(m["model"], {}).setdefault(d["column"], {})[
                    d["check"]] = {"duckdb": d["duckdb"], "bigquery": d["bigquery"]}
    return out


def loader_counts(path: Path) -> dict:
    """{'started': ts, 'tables': {table: (numRows, numBytes)}} from a loader log."""
    text = path.read_text()
    started = (re.findall(r"load_duckdb_real_sources\.sh\s+(\S+)", text) or ["?"])[0]
    tables = {m[0]: (int(m[1]), int(m[2])) for m in
              re.findall(r"^\s+(\w+)\s+numRows\s+(\d+)\s+numBytes\s+(\d+)", text, re.M)}
    return {"started": started, "tables": tables}


def kind_of(model: str, col: str):
    return ("float",) if (model, col) in FLOAT_COLS else ("decimal",)


def metric_name(col: str, check: str) -> str:
    return col + ("__sum" if check == "column_checksum" else "__distinct")


def compare_recorded(rec: dict, model: str, leg: str, got: dict) -> list:
    """Rows {model, column, check, leg, recorded, now, ok} for one model and one leg."""
    out = []
    for col, checks in sorted((rec["values"].get(model) or {}).items()):
        for check, v in sorted(checks.items()):
            now = got.get(metric_name(col, check))
            out.append({"model": model, "column": col, "check": check, "leg": leg,
                        "recorded": v[leg], "now": now, "ok": v[leg] == now})
    return out


def table_text(rows) -> str:
    lines = [f"{'leg':8s} {'model':34s} {'column':24s} {'check':22s} {'recorded':>18s}"
             f" {'now':>18s}  ok"]
    for r in rows:
        lines.append(f"{r['leg']:8s} {r['model']:34s} {r['column']:24s} {r['check']:22s}"
                     f" {r['recorded']!s:>18} {r['now']!s:>18}  {'ok' if r['ok'] else 'MISMATCH'}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- L9 build
def l9_validity(l2_db: Path) -> dict:
    """Is target/row_join/dev.duckdb's money9 still L9 of today's dev.duckdb?"""
    db = WORK / "dev.duckdb"
    proj_types = WORK / "project" / TYPES
    if not db.exists() or not proj_types.exists():
        return {"valid": False, "why": "no previous L9 build"}
    diff = subprocess.run(["git", "diff", "--no-index", "--no-color", str(TYPES),
                           str(proj_types.relative_to(REPO))], cwd=REPO,
                          capture_output=True, text=True).stdout
    changed = [ln for ln in diff.splitlines() if ln[:1] in "+-" and ln[:3] not in ("+++", "---")]
    if changed != ["-    decimal(18,2)", "+    decimal(38,9)"]:
        return {"valid": False, "why": f"scratch types.sql diff is not the one line: {changed}"}
    # Everything else the scratch copy was built from must still be the tracked tree.
    stale = []
    for f in filter(None, subprocess.run(["git", "ls-files", "-z", "models", "macros"],
                                         cwd=REPO, capture_output=True, check=True)
                    .stdout.decode().split("\0")):
        if f == str(TYPES):
            continue
        a, b = REPO / f, WORK / "project" / f
        if not b.exists() or a.read_bytes() != b.read_bytes():
            stale.append(f)
    if stale:
        return {"valid": False, "why": f"scratch project differs from the tree: {stale[:5]}"}
    src = {}
    for t in SOURCE_TABLES:
        cols = [(r["column_name"], parity.duck_kind(r["data_type"]), None) for r in ddb(
            l2_db, "SELECT column_name, data_type FROM information_schema.columns WHERE"
                   f" table_schema = 'thelook_ecommerce' AND table_name = '{t}'"
                   " AND data_type NOT IN ('GEOMETRY', 'BLOB')", readonly=True)]
        a = duck_metrics(l2_db, f"thelook_ecommerce.{q(t)}", cols, readonly=True)
        b = duck_metrics(db, f"thelook_ecommerce.{q(t)}", cols)
        src[t] = {"rows": a["__rows"], "columns": len(cols), "equal": a == b}
    n9 = ddb(db, "SELECT count(*) AS n FROM information_schema.tables"
                 " WHERE table_schema = 'money9'")[0]["n"]
    ok = all(v["equal"] for v in src.values()) and n9 >= 29
    return {"valid": ok, "why": "sources identical, money9 has all models" if ok else
            f"source tables differ or money9 incomplete ({n9} relations)",
            "sources": src, "money9_relations": n9, "diff": diff}


def build_l9(l2_db: Path) -> dict:
    proj = WORK / "project"
    if proj.exists():
        shutil.rmtree(proj)
    files = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True,
                           check=True).stdout.decode().split("\0")
    for f in filter(None, files):
        src = REPO / f
        if src.is_file():
            dst = proj / f
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    types = proj / TYPES
    text, n = re.subn(r"(\{% macro default__money_type\(\) -%\}\s*)decimal\(18,2\)",
                      r"\1decimal(38,9)", types.read_text())
    if n != 1:
        raise RuntimeError(f"expected exactly one default__money_type() body, replaced {n}")
    types.write_text(text)
    diff = subprocess.run(["git", "diff", "--no-index", "--no-color", str(TYPES),
                           str(types.relative_to(REPO))], cwd=REPO,
                          capture_output=True, text=True).stdout
    # The copy must be called dev.duckdb: the sources use target.database, which DuckDB
    # derives from the file name (models/staging/_thelook__sources.yml).
    db = WORK / "dev.duckdb"
    for p in (db, WORK / "dev.duckdb.wal"):
        if p.exists():
            p.unlink()
    shutil.copyfile(l2_db, db)
    (WORK / "profiles.yml").write_text(
        "bq_duckdb_experiments:\n  target: duckdb\n  outputs:\n    duckdb:\n"
        f"      type: duckdb\n      path: {db}\n      schema: money9\n      threads: 4\n"
        "      extensions:\n        - httpfs\n        - iceberg\n        - bigquery\n")
    env = parity.dbt_env()
    env["DBT_PROFILES_DIR"] = str(WORK)
    cmd = [str(parity.DBT), "build", "--target", "duckdb", "--project-dir", str(proj),
           "--profiles-dir", str(WORK), "--target-path", str(proj / "target"),
           "--log-path", str(WORK / "logs")]
    t0 = time.time()
    out = subprocess.run(cmd, cwd=proj, env=env, capture_output=True, text=True,
                         timeout=3600)
    wall = time.time() - t0
    body = out.stdout + ("\n# --- stderr ---\n" + out.stderr if out.stderr else "")
    write_log("l9_build.log", f"$ {' '.join(cmd)}\n# exit {out.returncode}, wall {wall:.2f} s\n"
              f"# the scratch project differs from the repository only by:\n{diff}\n{body}")
    summary = (re.findall(r"Summary: .*", body) or ["(no summary line)"])[-1]
    return {"exit": out.returncode, "summary": summary, "wall_s": round(wall, 2),
            "diff": diff, "built": "this run"}


# ------------------------------------------------------------------- pull
def pull(bq, db: Path, model: str, cols: list, kind: str) -> dict:
    sel = ", ".join(q(c) for c in cols)
    if kind == "TABLE":
        src = f"bigquery_scan('{RELATION}.{model}', billing_project := '{PROJECT}')"
        dry = None
    else:
        # bigquery_scan on a view: "non-table entities cannot be read with the storage API".
        # bigquery_query reads it, but an aggregate directly over it is an INTERNAL error
        # (probes/scan_view.py), so it is materialised first and measured from the copy.
        inner = "SELECT " + ", ".join(f"`{c}`" for c in cols) + f" FROM `{RELATION}.{model}`"
        dry = bq_dry_run(bq, inner)
        if dry > parity.MAX_BYTES:
            raise GateFailure(f"{model}: dry run says {dry} bytes > MAX_BYTES "
                              f"{parity.MAX_BYTES}; refusing")
        src = (f"bigquery_query('{PROJECT}', '{inner}', billing_project := '{PROJECT}',"
               " use_rest_api := true)")
    t0 = time.time()
    ddb(db, f"CREATE SCHEMA IF NOT EXISTS bq_leg;\n"
            f"CREATE OR REPLACE TABLE bq_leg.{q(model)} AS SELECT {sel} FROM {src};\n"
            f"SELECT 1 AS done;", bq=True)
    types = {r["column_name"]: r["data_type"] for r in ddb(
        db, "SELECT column_name, data_type FROM information_schema.columns "
            f"WHERE table_schema = 'bq_leg' AND table_name = '{model}'")}
    return {"via": "bigquery_scan" if kind == "TABLE" else "bigquery_query",
            "relation_type": kind, "dry_run_bytes": dry,
            "wall_s": round(time.time() - t0, 2), "types": types}


# ------------------------------------------------------------------- join
def join_model(db: Path, l2_db: Path, model: str, key: str, others: list, money: list):
    att = f"ATTACH IF NOT EXISTS '{l2_db}' AS l2 (READ_ONLY);\n"
    legs = {"l2": f"l2.main.{q(model)}", "l9": f"money9.{q(model)}",
            "bq": f"bq_leg.{q(model)}"}
    k = q(key)
    per_leg = {}
    for leg, rel in legs.items():
        per_leg[leg] = ddb(db, att + f"SELECT count(*) AS n, count(*) FILTER (WHERE {k} IS NULL)"
                           f" AS null_keys, count({k}) - count(DISTINCT {k}) AS dup_keys"
                           f" FROM {rel};")[0]
    sel = [f"coalesce(a.{k}, b.{k}, c.{k}) AS k",
           f"a.{k} IS NOT NULL AS in_l2", f"b.{k} IS NOT NULL AS in_l9",
           f"c.{k} IS NOT NULL AS in_bq"]
    for col in others + money:
        for alias, leg in (("a", "l2"), ("b", "l9"), ("c", "bq")):
            sel.append(f"{alias}.{q(col)} AS {q(col + '__' + leg)}")
    ddb(db, att + "CREATE SCHEMA IF NOT EXISTS rj;\n"
            f"CREATE OR REPLACE TABLE rj.{q(model)} AS SELECT {', '.join(sel)}\n"
            f"FROM {legs['l2']} a FULL JOIN {legs['l9']} b ON a.{k} = b.{k}\n"
            f"FULL JOIN {legs['bq']} c ON coalesce(a.{k}, b.{k}) = c.{k};\nSELECT 1 AS done;")
    agree = []
    for o in others:
        oo = {leg: q(f"{o}__{leg}") for leg in ("l2", "l9", "bq")}
        agree.append(f"count(*) FILTER (WHERE {oo['l2']} IS DISTINCT FROM {oo['bq']}"
                     f" OR {oo['l2']} IS DISTINCT FROM {oo['l9']}) AS {q('disagree__' + o)}")
    r = ddb(db, f"SELECT count(*) AS joined, count(*) FILTER (WHERE in_l2 AND in_l9 AND in_bq)"
                f" AS matched, count(*) FILTER (WHERE NOT (in_l2 AND in_l9 AND in_bq))"
                f" AS unmatched{''.join(', ' + a for a in agree)} FROM rj.{q(model)};")[0]
    other_disagree = {o: r.pop(f"disagree__{o}") for o in others}
    ok = (r["unmatched"] == 0 and len({v["n"] for v in per_leg.values()}) == 1
          and all(v["null_keys"] == 0 and v["dup_keys"] == 0 for v in per_leg.values())
          and not any(other_disagree.values()))
    return {"per_leg": per_leg, **r, "other_keys_disagree": other_disagree, "ok": ok}


def bucket_sql(model: str, col: str) -> dict:
    l2, l9, bq = (q(f"{col}__{s}") for s in ("l2", "l9", "bq"))
    if (model, col) in FLOAT_COLS:  # the harness's float rule: micro-units
        e = lambda x: f"CAST(round({x} * 1000000) AS BIGINT)"  # noqa: E731
        rb, cl2, l9_eq = e(bq), e(l2), f"{e(l9)} IS NOT DISTINCT FROM {e(bq)}"
    else:                           # decimal: cents; L9 = BQ at nine decimals, exactly
        rb, cl2, l9_eq = f"round({bq}, 2)", l2, f"{l9} IS NOT DISTINCT FROM {bq}"
    cents_differ = f"{rb} IS DISTINCT FROM {cl2}"
    return {
        "identical": f"{bq} IS NOT DISTINCT FROM {l2}",
        "A": f"{bq} IS DISTINCT FROM {l2} AND {rb} IS NOT DISTINCT FROM {cl2}",
        "B": f"{cents_differ} AND {l9_eq}",
        "C": f"{cents_differ} AND NOT ({l9_eq})",
        "cents_differ": cents_differ,
        "raw_differ": f"{bq} IS DISTINCT FROM {l2}",
        "l9_equals_bq": l9_eq,
        "delta": f"{rb} - {cl2}",
        "l9_minus_bq": f"{l9} - {bq}",
    }


def column_report(db: Path, l2_db: Path, model: str, col: str, key: str) -> dict:
    s = bucket_sql(model, col)
    t = f"rj.{q(model)}"
    both = "in_l2 AND in_l9 AND in_bq"
    l2, l9, bq = (q(f"{col}__{x}") for x in ("l2", "l9", "bq"))
    counts = ddb(db, "SELECT count(*) AS rows_compared, "
                 + ", ".join(f"count(*) FILTER (WHERE {s[b]}) AS {q(b)}"
                             for b in ("cents_differ", "raw_differ", "identical", "A", "B", "C",
                                       "l9_equals_bq"))
                 + f", count(*) FILTER (WHERE {l2} IS NULL AND {bq} IS NULL) AS null_both"
                 + f", count(*) FILTER (WHERE ({l2} IS NULL) <> ({bq} IS NULL)"
                 + f" OR ({l9} IS NULL) <> ({bq} IS NULL)) AS null_one_side"
                 + f" FROM {t} WHERE {both};")[0]
    dist = ddb(db, f"SELECT CAST({s['delta']} AS VARCHAR) AS delta, count(*) AS n FROM {t}"
                   f" WHERE {both} GROUP BY {s['delta']} ORDER BY {s['delta']};")
    examples = ddb(db, f"SELECT CAST(k AS VARCHAR) AS key, CAST({l2} AS VARCHAR) AS l2,"
                       f" CAST({l9} AS VARCHAR) AS l9, CAST({bq} AS VARCHAR) AS bq,"
                       f" CASE WHEN {s['C']} THEN 'C' ELSE 'B' END AS bucket FROM {t}"
                       f" WHERE {both} AND {s['cents_differ']}"
                       f" ORDER BY ({s['C']}) DESC, k LIMIT {EXAMPLES};")
    if not examples:  # no cent differs: show A rows instead, so the scale is visible
        examples = ddb(db, f"SELECT CAST(k AS VARCHAR) AS key, CAST({l2} AS VARCHAR) AS l2,"
                           f" CAST({l9} AS VARCHAR) AS l9, CAST({bq} AS VARCHAR) AS bq,"
                           f" 'A' AS bucket FROM {t} WHERE {both} AND {s['A']}"
                           f" ORDER BY k LIMIT {EXAMPLES};")
    out = {"model": model, "column": col, "key": key,
           "compare": ("float_type(), compared at 1e-6 (round(x*1e6)::BIGINT); delta in"
                       " 1e-6 units" if (model, col) in FLOAT_COLS
                       else "money_type(); delta in dollars, at cents"),
           **counts, "delta_distribution": dist, "examples": examples}
    out["invariants"] = {
        "identical+A+B+C=rows_compared": counts["identical"] + counts["A"] + counts["B"]
        + counts["C"] == counts["rows_compared"],
        "A+B+C=raw_differ": counts["A"] + counts["B"] + counts["C"] == counts["raw_differ"],
        "B+C=cents_differ": counts["B"] + counts["C"] == counts["cents_differ"]}
    out["c_analysis"] = c_analysis(db, l2_db, model, col, s, counts["C"])
    # Rows where the emulation is not BigQuery, whatever their bucket (an A row can have
    # L9 != BQ: then L2 and BigQuery agree in cents and L9 does not).
    n_off = counts["rows_compared"] - counts["l9_equals_bq"]
    by_bucket = ddb(db, "SELECT " + ", ".join(
        f"count(*) FILTER (WHERE {s[b]}) AS {q(b)}" for b in ("identical", "A", "B", "C"))
        + f" FROM {t} WHERE {both} AND NOT ({s['l9_equals_bq']});")[0] if n_off else {}
    out["l9_not_bq"] = {"rows": n_off, "by_bucket": by_bucket, "detail": division_rows(db, model, col, s) if n_off
                        and (model, col) in DIVISIONS else ddb(
        db, f"SELECT CAST(k AS VARCHAR) AS key, CAST({l2} AS VARCHAR) AS l2,"
            f" CAST({l9} AS VARCHAR) AS l9, CAST({bq} AS VARCHAR) AS bq FROM {t}"
            f" WHERE {both} AND NOT ({s['l9_equals_bq']}) ORDER BY k LIMIT 50;") if n_off else []}
    return out


def division_rows(db: Path, model: str, col: str, s: dict) -> list:
    """For round(num / n, 2) rows where L9 != BQ: the quotient on each engine's rule.

    DuckDB: DECIMAL / BIGINT is DOUBLE, then round(double, 2). BigQuery: NUMERIC / INT64
    is NUMERIC, i.e. the quotient rounded to nine decimals (half away from zero) first,
    then ROUND(numeric, 2). The NUMERIC rule is computed exactly, on integers.
    """
    num, den = DIVISIONS[(model, col)]
    t = f"rj.{q(model)}"
    a = f"CAST(j.{q(num + '__l9')} * 1000000000 AS HUGEINT)"
    n = f"CAST(m.{q(den)} AS HUGEINT)"
    q9 = f"(sign({a}) * ((2 * abs({a}) + {n}) // (2 * {n})))"
    num9 = f"CAST(CAST({q9} AS DECIMAL(38,9)) * 0.000000001 AS DECIMAL(38,9))"
    cond = s["l9_equals_bq"].replace('"' + col, 'j."' + col)
    return ddb(db, f"SELECT CAST(j.k AS VARCHAR) AS key,"
                   f" CAST(j.{q(num + '__l9')} AS VARCHAR) AS numerator_l9,"
                   f" CAST(j.{q(num + '__bq')} AS VARCHAR) AS numerator_bq,"
                   f" CAST(j.{q(num + '__l2')} AS VARCHAR) AS numerator_l2,"
                   f" CAST(j.{q(num + '__l2')} / m.{q(den)} AS VARCHAR) AS l2_double_quotient,"
                   f" CAST(m.{q(den)} AS VARCHAR) AS denominator,"
                   f" CAST(j.{q(num + '__l9')} / m.{q(den)} AS VARCHAR) AS duckdb_double_quotient,"
                   f" CAST({num9} AS VARCHAR) AS numeric_quotient_9dp,"
                   f" CAST(round(j.{q(num + '__l9')} / m.{q(den)}, 2) AS VARCHAR) AS duckdb_cents,"
                   f" CAST(round({num9}, 2) AS VARCHAR) AS numeric_rule_cents,"
                   f" CAST(j.{q(col + '__l2')} AS VARCHAR) AS l2,"
                   f" CAST(j.{q(col + '__l9')} AS VARCHAR) AS l9,"
                   f" CAST(j.{q(col + '__bq')} AS VARCHAR) AS bq,"
                   f" (round({num9}, 2) = j.{q(col + '__bq')}"
                   f" AND round(j.{q(num + '__l9')} / m.{q(den)}, 2) = j.{q(col + '__l9')})"
                   f" AS division_rule_explains"
                   f" FROM {t} j JOIN money9.{q(model)} m ON m.{q(_KEYS[model])} = j.k"
                   f" WHERE j.in_l2 AND j.in_l9 AND j.in_bq AND NOT ({cond}) ORDER BY j.k;")


def c_analysis(db, l2_db, model, col, s, n_c) -> dict:
    """The verdict for a column's C rows.

    direct cast: the raw FLOAT64 in dev.duckdb is recomputed on both paths; a C row is
      explained when cast(x as decimal(18,2)) is L2 and round(cast(x as decimal(38,9)), 2)
      is BigQuery's cents. All explained -> emulation imperfect; else genuinely different.
    derived: the column's SQL line and the L9 - BQ distribution over its C rows. A C row
      is emulation-imperfect when L9 and BigQuery differ by less than one cent (1e-6 for the
      float) - the two engines type the same arithmetic differently - and genuinely
      different otherwise; the column verdict is the worst of its rows.
    """
    t = f"rj.{q(model)}"
    both = "in_l2 AND in_l9 AND in_bq"
    l2, l9, bq = (q(f"{col}__{x}") for x in ("l2", "l9", "bq"))
    att = f"ATTACH IF NOT EXISTS '{l2_db}' AS l2 (READ_ONLY);\n"
    if (model, col) in LINEAGE:
        stab, scol, skey, via = LINEAGE[(model, col)]
        x = f"s.{q(scol)}"
        src = (f"FROM {t} j JOIN l2.main.{q(model)} a ON j.k = a.{q(_KEYS[model])}"
               f" JOIN l2.thelook_ecommerce.{q(stab)} s ON s.{q(skey)} = a.{q(via)}")
        check = ddb(db, att + f"SELECT count(*) AS n, count(*) FILTER (WHERE"
                    f" CAST({x} AS DECIMAL(18,2)) IS DISTINCT FROM j.{l2}) AS l2_not_cast,"
                    f" count(*) FILTER (WHERE CAST({x} AS DECIMAL(38,9)) IS DISTINCT FROM j.{l9})"
                    f" AS l9_not_cast, count(*) FILTER (WHERE CAST({x} AS DECIMAL(38,9))"
                    f" IS DISTINCT FROM j.{bq}) AS bq_not_cast9 {src} WHERE j.{both.replace(' AND ', ' AND j.')};")[0]
        jc = (s["C"].replace(l2, "j." + l2).replace(l9, "j." + l9).replace(bq, "j." + bq))
        rows = ddb(db, att + f"SELECT CAST(j.k AS VARCHAR) AS key, CAST({x} AS VARCHAR) AS source,"
                   f" CAST(j.{l2} AS VARCHAR) AS l2, CAST(j.{l9} AS VARCHAR) AS l9,"
                   f" CAST(j.{bq} AS VARCHAR) AS bq,"
                   f" CAST(CAST({x} AS DECIMAL(18,2)) AS VARCHAR) AS path_2,"
                   f" CAST(round(CAST({x} AS DECIMAL(38,9)), 2) AS VARCHAR) AS path_9_to_2,"
                   f" (CAST({x} AS DECIMAL(18,2)) = j.{l2} AND"
                   f" round(CAST({x} AS DECIMAL(38,9)), 2) = round(j.{bq}, 2)) AS base_explains"
                   f" {src} WHERE j.{both.replace(' AND ', ' AND j.')} AND {jc}"
                   f" ORDER BY j.k;") if n_c else []
        explained = sum(1 for r in rows if r["base_explains"])
        verdict = ("no C rows" if not n_c else
                   "emulation imperfect" if explained == n_c else "genuinely different")
        return {"lineage": "direct cast", "source": f"thelook_ecommerce.{stab}.{scol}",
                "sql_line": sql_line(model, col), "lineage_check": check, "c_rows": rows,
                "base_explains": explained, "verdict": verdict}
    diag = ddb(db, f"SELECT CAST({s['l9_minus_bq']} AS VARCHAR) AS l9_minus_bq, count(*) AS n"
                   f" FROM {t} WHERE {both} AND {s['C']} GROUP BY {s['l9_minus_bq']}"
                   f" ORDER BY {s['l9_minus_bq']};") if n_c else []
    rows = ddb(db, f"SELECT CAST(k AS VARCHAR) AS key, CAST({l2} AS VARCHAR) AS l2,"
                   f" CAST({l9} AS VARCHAR) AS l9, CAST({bq} AS VARCHAR) AS bq,"
                   f" CAST({s['l9_minus_bq']} AS VARCHAR) AS l9_minus_bq FROM {t}"
                   f" WHERE {both} AND {s['C']} ORDER BY k;") if n_c else []
    limit = 0.000001 if (model, col) in FLOAT_COLS else 0.01
    worst = max((abs(float(r["l9_minus_bq"])) for r in diag), default=0.0)
    verdict = ("no C rows" if not n_c else
               "emulation imperfect" if worst < limit else "genuinely different")
    return {"lineage": "derived", "sql_line": sql_line(model, col), "l9_minus_bq": diag,
            "max_abs_l9_minus_bq": worst, "c_rows": rows, "verdict": verdict}


def sql_line(model: str, col: str) -> str:
    """file:line of the select-list entry that produces `col` in the model."""
    path = next((REPO / "models").rglob(f"{model}.sql"), None)
    if not path:
        return "?"
    lines = path.read_text().splitlines()
    pats = [rf"\bas\s+{re.escape(col)}\b", rf"^\s*[\w.]*\.{re.escape(col)}\s*,?\s*$",
            rf"^\s*{re.escape(col)}\s*,?\s*$"]
    for pat in pats:
        for i in range(len(lines) - 1, -1, -1):
            if re.search(pat, lines[i], re.I):
                # a cast that spans lines: quote from the line the expression starts on
                start = i
                while start > 0 and lines[start].strip().startswith("as ") :
                    start -= 1
                text = " ".join(ln.strip() for ln in lines[start:i + 1])
                return f"{path.relative_to(REPO)}:{start + 1}: {text}"
    return f"{path.relative_to(REPO)}: (not found)"


# --------------------------------------------------------------- base control
def base_control(l2_db: Path) -> list:
    out = []
    for tab, col in BASE_CONTROL:
        x = q(col)
        cond = f"CAST({x} AS DECIMAL(18,2)) <> round(CAST({x} AS DECIMAL(38,9)), 2)"
        r = ddb(l2_db, f"SELECT count(*) AS n, count(*) FILTER (WHERE {cond}) AS changes,"
                       f" (SELECT string_agg(v || ' (' || c || ' rows: '"
                       f" || p2 || ' vs ' || p9 || ')', '; ' ORDER BY v) FROM"
                       f" (SELECT CAST({x} AS VARCHAR) AS v, count(*) AS c,"
                       f" CAST(CAST({x} AS DECIMAL(18,2)) AS VARCHAR) AS p2,"
                       f" CAST(round(CAST({x} AS DECIMAL(38,9)), 2) AS VARCHAR) AS p9"
                       f" FROM thelook_ecommerce.{q(tab)} WHERE {cond} GROUP BY ALL)) AS examples"
                       f" FROM thelook_ecommerce.{q(tab)};", readonly=True)[0]
        out.append({"source": f"{tab}.{col}", **r})
    return out


# ------------------------------------------------------------------ gates
def source_gate(bq, l2_db: Path) -> dict:
    """dev.duckdb's thelook_ecommerce is today's bigquery-public-data.thelook_ecommerce."""
    rows, ok = [], True
    for t in SOURCE_TABLES:
        meta = bq_api(bq, f"bigquery-public-data/datasets/thelook_ecommerce/tables/{t}")
        local = ddb(l2_db, f"SELECT count(*) AS n FROM thelook_ecommerce.{q(t)}",
                    readonly=True)[0]["n"]
        r = {"table": t, "bigquery_rows": int(meta["numRows"]),
             "bigquery_bytes": int(meta["numBytes"]), "duckdb_rows": local,
             "rows_equal": int(meta["numRows"]) == local}
        if t in SOURCE_MONEY:
            measured = [(c, ("int",) if c == "id" else ("float",), None) for c in SOURCE_MONEY[t]]
            b = bq_metrics(bq, f"`bigquery-public-data.thelook_ecommerce.{t}`", measured)
            d = duck_metrics(l2_db, f"thelook_ecommerce.{q(t)}", measured, readonly=True)
            r["money_columns"] = SOURCE_MONEY[t]
            r["metrics_equal"] = b == d
            if b != d:
                r["metrics_diff"] = {k: (d[k], b[k]) for k in b if b[k] != d.get(k)}
        ok = ok and r["rows_equal"] and r.get("metrics_equal", True)
        rows.append(r)
    return {"ok": ok, "tables": rows}


def of_record_finding(bq, l2_db: Path, l2_types: dict, keys: dict) -> dict:
    """The recomputation that stops nothing now: of-record values vs today's legs."""
    rec = recorded(OF_RECORD)
    rows, counts = [], []
    for model in sorted(rec["values"]):
        measured = [(c, kind_of(model, c), None) for c in sorted(rec["values"][model])]
        b = bq_metrics(bq, f"`{rec['relation']}.{model}`", measured)
        d = duck_metrics(l2_db, f"main.{q(model)}", measured, readonly=True)
        rows += compare_recorded(rec, model, "bigquery", b) + compare_recorded(rec, model, "duckdb", d)
        counts.append({"model": model, "recorded": rec["rows"].get(model),
                       "of_record_bigquery_now": b["__rows"], "l2_now": d["__rows"]})
    write_log("of_record_gate.log",
              f"# of-record relation {rec['relation']} ({rec['generated_at']}) vs today\n"
              "# row counts: recorded (duckdb, bigquery) | of-record BigQuery now | L2 now\n"
              + "".join(f"  {c['model']:34s} {c['recorded']} | {c['of_record_bigquery_now']}"
                        f" | {c['l2_now']}\n" for c in counts) + "\n" + table_text(rows))
    return {"relation": rec["relation"], "generated_at": rec["generated_at"],
            "bigquery_ok": sum(r["ok"] for r in rows if r["leg"] == "bigquery"),
            "bigquery_total": sum(1 for r in rows if r["leg"] == "bigquery"),
            "duckdb_ok": sum(r["ok"] for r in rows if r["leg"] == "duckdb"),
            "duckdb_total": sum(1 for r in rows if r["leg"] == "duckdb"),
            "row_counts": counts, "mismatches": [r for r in rows if not r["ok"]]}


# ------------------------------------------------------------------ reports
def md_table(rows, cols) -> list:
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        out.append("| " + " | ".join(str(r.get(c, "")) for c in cols) + " |")
    return out


def write_reports(rep: dict) -> None:
    (VP / "rows.json").write_text(json.dumps(rep, indent=1, default=str) + "\n")
    L: list[str] = []
    A = L.append
    A("# Row-by-row join of the two value-parity legs (card t_48e969eb)")
    A("")
    A(f"Generated {rep['generated_at']} by `DBT_ENV={rep['dbt_env']} python3 scripts/row_join.py`"
      f" (`make row-join DBT_ENV={rep['dbt_env']}`). DuckDB leg: `dev.duckdb`; BigQuery leg:"
      f" `{rep['relation']}`; the fresh parity run of the same pair:"
      f" `analyses/value_parity/fresh/results.md` ({rep['fresh']['generated_at']}).")
    A("")
    A("## Verdict")
    A("")
    for line in rep["verdict"]:
        A(line)
    A("")
    if rep.get("drift"):
        dr = rep["drift"]
        A("## Why this is a fresh pair: the source moved after the of-record run")
        A("")
        A(f"The of-record pair (`results.md`, BigQuery leg `{rep['of_record']['relation']}`)"
          " can no longer be joined row by row. `bigquery-public-data.thelook_ecommerce`"
          f" grew between the of-record load ({dr['of_record_started']},"
          " `logs/loader.log`) and this pair's load"
          f" ({dr['fresh_started']}, `logs/row_join_loader.log`); the of-record BigQuery"
          " tables are frozen at the old rows, its views and any DuckDB load read the new ones:")
        A("")
        L.extend(md_table(dr["tables"], ["table", "rows of record", "rows now", "growth",
                                         "bytes of record", "bytes now"]))
        A("")
        o = rep["of_record"]
        A(f"Recomputing the of-record values today (`logs/rows/of_record_gate.log`): on"
          f" `{o['relation']}` {o['bigquery_ok']} of {o['bigquery_total']} recorded BigQuery"
          f" values reproduce (all misses are views, which read the live source); on today's"
          f" `dev.duckdb` {o['duckdb_ok']} of {o['duckdb_total']} recorded DuckDB values do."
          " Row counts that moved:")
        A("")
        moved = [c for c in o["row_counts"] if c["recorded"].get("duckdb") != c["l2_now"]
                 or c["recorded"].get("bigquery") != c["of_record_bigquery_now"]]
        L.extend(md_table([{"model": c["model"],
                            "recorded (both legs)": c["recorded"].get("bigquery"),
                            "of-record BigQuery now": c["of_record_bigquery_now"],
                            "dev.duckdb now": c["l2_now"]} for c in moved],
                          ["model", "recorded (both legs)", "of-record BigQuery now",
                           "dev.duckdb now"]))
        A("")
    A("## Gates")
    A("")
    g = rep["gates"]
    A(f"* **source** ({'pass' if g['source']['ok'] else 'FAIL'}): the seven"
      " `thelook_ecommerce` tables in `dev.duckdb` have today's BigQuery row count, and the"
      " money source columns (and `id`) hash identically on both sides"
      " (`parity.metrics_sql`, float rule):")
    A("")
    L.extend(md_table([{**t, "money_columns": ", ".join(t.get("money_columns", [])) or "-",
                        "metrics_equal": t.get("metrics_equal", "-")}
                       for t in g["source"]["tables"]],
                      ["table", "bigquery_rows", "duckdb_rows", "rows_equal", "money_columns",
                       "metrics_equal"]))
    A("")
    A(f"* **rows** ({'pass' if g['rows']['ok'] else 'FAIL'}): per model, L2 = BigQuery (REST)"
      f" = the fresh run's recorded count, {g['rows']['models']} models.")
    A(f"* **transfer** ({'pass' if g['transfer']['ok'] else 'FAIL'}): `bq_leg.<model>`,"
      " measured in DuckDB with `metrics_sql`, equals the REST measurement of the same relation"
      f" on every pulled column ({g['transfer']['metrics']} metrics over"
      f" {g['transfer']['models']} models); the REST measurement reproduces"
      f" {g['transfer']['fresh_ok']} of {g['transfer']['fresh_total']} values the fresh run"
      " recorded"
      + (f" (`{', '.join(g['transfer']['fresh_unrecorded'])}` has no recorded values: the fresh"
         " run left it not_measured, see challenges)" if g['transfer']['fresh_unrecorded'] else "")
      + ".")
    A(f"* L2 is the fresh run's DuckDB leg: {g['l2_fresh']['ok']} of {g['l2_fresh']['total']}"
      " recorded DuckDB values reproduce on today's `dev.duckdb`.")
    A("")
    l9 = rep["l9"]
    A("## L9: the DuckDB build with money_type() = decimal(38,9)")
    A("")
    A(f"A copy of the tracked tree under `target/row_join/project/` built into schema `money9`"
      f" of a copy of `dev.duckdb` ({l9['build']}). Validity against today's `dev.duckdb`:"
      f" {l9['validity']}. Every one of the {rep['money_column_count'] - 1} money_type()"
      " columns is `DECIMAL(38,9)` in `money9`. The copy differs from the repository only by:")
    A("")
    A("```diff")
    A(l9["diff"].rstrip())
    A("```")
    A("")
    A("## Per model")
    A("")
    A("| model | key | BQ read | rows L2 / L9 / BQ | unmatched | null / dup keys | money cols |"
      " identical | A | B | C |")
    A("|---|---|---|---|---:|---|---:|---:|---:|---:|---:|")
    for m in rep["models"]:
        j, pl, tot = m["join"], m["join"]["per_leg"], m["totals"]
        A(f"| {m['model']} | `{m['key']}`"
          + (f" (+`{'`, `'.join(m['other_unique_keys'])}` agree)" if m["other_unique_keys"] else "")
          + f" | {m['pull']['via']} | {pl['l2']['n']} / {pl['l9']['n']} / {pl['bq']['n']} |"
          f" {j['unmatched']} | {sum(v['null_keys'] for v in pl.values())} /"
          f" {sum(v['dup_keys'] for v in pl.values())} | {len(m['columns'])} |"
          f" {tot['identical']} | {tot['A']} | {tot['B']} | {tot['C']} |")
    t = rep["totals"]
    A(f"| **total** | | | | | | **{t['columns']}** | **{t['identical']}** | **{t['A']}** |"
      f" **{t['B']}** | **{t['C']}** |")
    A("")
    A("## Per column")
    A("")
    A("Summary (rows compared = rows present on all three legs):")
    A("")
    def span(c):
        ds = [float(d["delta"]) for d in c["delta_distribution"] if d["delta"] is not None]
        return f"{min(ds):+.2f} .. {max(ds):+.2f}" if ds and (min(ds) or max(ds)) else "0"
    L.extend(md_table([{"column": f"`{c['model']}.{c['column']}`", "rows": c["rows_compared"],
                        "cents differ": c["cents_differ"], "delta range": span(c),
                        "raw differs": c["raw_differ"],
                        "identical": c["identical"], "A": c["A"], "B": c["B"], "C": c["C"],
                        "L9 = BQ": c["l9_equals_bq"], "NULL both / one side":
                        f"{c['null_both']} / {c['null_one_side']}",
                        "C verdict": c["c_analysis"]["verdict"]}
                       for m in rep["models"] for c in m["columns"]],
                      ["column", "rows", "cents differ", "delta range", "raw differs",
                       "identical", "A", "B", "C", "L9 = BQ", "NULL both / one side",
                       "C verdict"]))
    A("")
    A("`delta range` is in dollars (1e-6 units for `gross_margin_rate`); a NULL on both legs"
      " is `identical` and its delta is NULL.")
    A("")
    for m in rep["models"]:
        for c in m["columns"]:
            ca = c["c_analysis"]
            A(f"### `{m['model']}.{c['column']}`")
            A("")
            A(f"{c['compare']}. Rows {c['rows_compared']}; cents differ {c['cents_differ']};"
              f" raw differs {c['raw_differ']}. identical {c['identical']}, A {c['A']},"
              f" B {c['B']}, C {c['C']}; L9 = BQ exactly on {c['l9_equals_bq']} rows."
              f" Invariants: {', '.join(k + (' holds' if v else ' FAILS') for k, v in c['invariants'].items())}.")
            A(f"Lineage: {ca['lineage']}, `{ca['sql_line']}`"
              + (f"; source `{ca['source']}`, checked on every row: {ca['lineage_check']}"
                 if ca["lineage"] == "direct cast" else "")
              + f". C verdict: **{ca['verdict']}**.")
            A("")
            A("delta → rows: " + ", ".join(f"`{d['delta'] if d['delta'] is not None else 'NULL'}` → {d['n']}"
                                          for d in c["delta_distribution"]))
            A("")
            if c["examples"]:
                L.extend(md_table(c["examples"], ["key", "l2", "l9", "bq", "bucket"]))
                A("")
            if ca.get("l9_minus_bq"):
                A("L9 − BQ over the C rows: " + ", ".join(
                    f"`{d['l9_minus_bq']}` → {d['n']}" for d in ca["l9_minus_bq"]))
                A("")
            if ca.get("c_rows"):
                A(f"C rows ({len(ca['c_rows'])}"
                  + (", first 50; all in `rows.json`" if len(ca["c_rows"]) > 50 else "") + "):")
                A("")
                L.extend(md_table(ca["c_rows"][:50], list(ca["c_rows"][0].keys())))
                A("")
    A("## Where L9 is not BigQuery")
    A("")
    off = [c for m in rep["models"] for c in m["columns"] if c["l9_not_bq"]["rows"]]
    if not off:
        A("Nowhere: L9 equals BigQuery exactly on every compared row.")
    for c in off:
        A(f"`{c['model']}.{c['column']}`: {c['l9_not_bq']['rows']} rows (`{c['c_analysis']['sql_line']}`)."
          " Their buckets (decided by L2 against BigQuery; L9 only separates B from C): "
          + ", ".join(f"{b} {n}" for b, n in c["l9_not_bq"]["by_bucket"].items()) + ".")
        A("")
        if c["l9_not_bq"]["detail"]:
            L.extend(md_table(c["l9_not_bq"]["detail"], list(c["l9_not_bq"]["detail"][0].keys())))
            A("")
    for line in rep.get("l9_off_lines", []):
        A(line)
    A("")
    A("## Base-value control (raw FLOAT64 in dev.duckdb)")
    A("")
    A("Values whose cent differs between `cast(x as decimal(18,2))` (one rounding) and"
      " `round(cast(x as decimal(38,9)), 2)` (through nine decimals):")
    A("")
    L.extend(md_table(rep["base_control"], ["source", "n", "changes", "examples"]))
    A("")
    A("## The answer")
    A("")
    for line in rep["answer_lines"]:
        A(line)
    A("")
    A("## Proposal (unapplied)")
    A("")
    for line in rep["proposal"]:
        A(line)
    A("")
    A("## Reproduce")
    A("")
    A("```")
    A("BQ_KEYFILE=<key> DBT_ENV=rows make value-parity   # the pair (analyses/value_parity/fresh/)")
    A("BQ_KEYFILE=<key> DBT_ENV=rows make row-join       # this report")
    A("```")
    (VP / "rows.md").write_text("\n".join(L) + "\n")


# --------------------------------------------------------------------- main
def main() -> int:
    global KEY
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rebuild-l9", action="store_true",
                    help="rebuild L9 even when the previous build is still valid")
    args = ap.parse_args()
    KEY = os.environ.get("BQ_KEYFILE") or ""
    if not KEY or not Path(KEY).is_file():
        print("BQ_KEYFILE is not set to a readable key file")
        return 2
    rep = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "dbt_env": os.environ.get("DBT_ENV", "dev"), "relation": RELATION}
    LOGS.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    try:
        return _main(args, REPO / "dev.duckdb", rep)
    except GateFailure as e:
        log(f"GATE FAILED: {e}")
        return 2
    finally:
        write_log("run.log", "\n".join(_log_lines) + "\n")


def _main(args, l2_db: Path, rep: dict) -> int:
    log(f"row_join.py  L2 dev.duckdb  BQ {RELATION}")
    if RELATION.endswith(".experiments_dev"):
        raise GateFailure("DBT_ENV is dev: that dataset is the of-record leg, whose source has"
                          " moved; run the fresh pair with DBT_ENV=rows")
    # -- 0. preconditions
    if not l2_db.exists():
        raise GateFailure("dev.duckdb does not exist")
    problem = parity.real_sources_problem(parity.DuckLeg(l2_db))
    if problem:
        raise GateFailure(problem)
    fresh = recorded(FRESH)
    rep["fresh"] = {"generated_at": fresh["generated_at"], "relation": fresh["relation"],
                    "not_measured": fresh["not_measured"]}
    if fresh["relation"] != RELATION:
        raise GateFailure(f"{FRESH.relative_to(REPO)} measured {fresh['relation']}, not {RELATION}")
    keys = manifest_keys()
    l2_types: dict = {}
    for r in ddb(l2_db, "SELECT table_name, column_name, data_type FROM information_schema.columns"
                        " WHERE table_schema = 'main'", readonly=True):
        l2_types.setdefault(r["table_name"], {})[r["column_name"]] = (
            parity.duck_kind(r["data_type"]), r["data_type"])
    if len(l2_types) < 29:
        raise GateFailure(f"main in dev.duckdb holds {len(l2_types)} relations, not 29")
    money = {(m, c) for m, cols in l2_types.items() for c, (_, t) in cols.items()
             if t == "DECIMAL(18,2)"} | FLOAT_COLS
    models = sorted({m for m, _ in money})
    rep["money_column_count"] = len(money)
    log(f"  {len(money)} money columns in {len(models)} models"
        f" ({len(money) - len(FLOAT_COLS)} DECIMAL(18,2) + gross_margin_rate)")
    for m in models:
        ks = keys.get(m, [])
        if not ks:
            raise GateFailure(f"{m}: no unique test in target/manifest.json")
        if (m, ks[0]) in money:
            raise GateFailure(f"{m}: key {ks[0]} is a money column")
        _KEYS[m] = ks[0]
    bq = parity.BigQueryLeg(KEY, PROJECT)
    dataset = RELATION.split(".")[1]
    rels = {t["tableReference"]["tableId"]: t["type"]
            for t in bq_api(bq, f"{PROJECT}/datasets/{dataset}/tables")["tables"]}
    for m in models:
        fields = {f["name"]: f["type"] for f in
                  bq_api(bq, f"{PROJECT}/datasets/{dataset}/tables/{m}")["schema"]["fields"]}
        for mm, c in money:
            want = "FLOAT" if (mm, c) in FLOAT_COLS else "NUMERIC"
            if mm == m and fields.get(c) != want:
                raise GateFailure(f"{m}.{c}: BigQuery says {fields.get(c)}, expected {want}")

    # -- drift: the two loader logs; of-record recomputation (finding, not a stop)
    a, b = loader_counts(LOADER_OF_RECORD), loader_counts(LOADER_FRESH)
    rep["drift"] = {"of_record_started": a["started"], "fresh_started": b["started"],
                    "tables": [{"table": t, "rows of record": a["tables"][t][0],
                                "rows now": b["tables"][t][0],
                                "growth": b["tables"][t][0] - a["tables"][t][0],
                                "bytes of record": a["tables"][t][1],
                                "bytes now": b["tables"][t][1]} for t in SOURCE_TABLES]}
    log("of-record recomputation (reported, not a gate)")
    rep["of_record"] = of_record_finding(bq, l2_db, l2_types, keys)
    o = rep["of_record"]
    log(f"  of-record: BigQuery {o['bigquery_ok']}/{o['bigquery_total']},"
        f" DuckDB {o['duckdb_ok']}/{o['duckdb_total']} recorded values reproduce")

    # -- gate: source
    log("gate source: dev.duckdb thelook_ecommerce = bigquery-public-data.thelook_ecommerce now")
    rep["gates"] = {"source": source_gate(bq, l2_db)}
    for t in rep["gates"]["source"]["tables"]:
        log(f"  {t['table']:22s} rows bq {t['bigquery_rows']:>8} duckdb {t['duckdb_rows']:>8}"
            f"  money metrics {t.get('metrics_equal', '-')}")
    if not rep["gates"]["source"]["ok"]:
        write_log("gates.log", json.dumps(rep["gates"], indent=1) + "\n")
        raise GateFailure("dev.duckdb's source rows are not today's BigQuery rows")

    # -- gate: rows (REST metrics of every pulled column; also the transfer reference)
    log("gate rows: L2 = BigQuery (REST) = fresh record, per model")
    rest, row_rows, l2_fresh = {}, [], []
    fresh_rows = []
    for m in models:
        cols = keys[m] + sorted(c for mm, c in money if mm == m)
        measured = [(c, kind_of(m, c) if c not in keys[m] else l2_types[m][c][0], None)
                    for c in cols]
        rest[m] = (measured, bq_metrics(bq, f"`{RELATION}.{m}`", measured))
        d = duck_metrics(l2_db, f"main.{q(m)}", measured, readonly=True)
        rec_n = fresh["rows"].get(m, {})
        ok = (d["__rows"] == rest[m][1]["__rows"] == rec_n.get("duckdb")
              and rec_n.get("bigquery") in (None, d["__rows"]))
        row_rows.append({"model": m, "l2": d["__rows"], "bigquery": rest[m][1]["__rows"],
                         "fresh_recorded": rec_n, "ok": ok})
        fresh_rows += compare_recorded(fresh, m, "bigquery", rest[m][1])
        l2_fresh += compare_recorded(fresh, m, "duckdb", d)
        log(f"  {m:34s} L2 {d['__rows']:>7}  BQ {rest[m][1]['__rows']:>7}"
            f"  fresh {rec_n}  {'ok' if ok else 'MISMATCH'}")
    rep["gates"]["rows"] = {"ok": all(r["ok"] for r in row_rows), "models": len(row_rows),
                            "per_model": row_rows}
    rep["gates"]["l2_fresh"] = {"ok": sum(r["ok"] for r in l2_fresh), "total": len(l2_fresh),
                                "mismatches": [r for r in l2_fresh if not r["ok"]]}
    write_log("gates.log", "# rows gate\n" + json.dumps(row_rows, indent=1)
              + "\n\n# fresh-record values: REST now vs recorded (bigquery), dev.duckdb now vs"
              " recorded (duckdb)\n" + table_text(fresh_rows + l2_fresh))
    if not rep["gates"]["rows"]["ok"]:
        raise GateFailure("row counts differ between the legs")
    if rep["gates"]["l2_fresh"]["ok"] != rep["gates"]["l2_fresh"]["total"]:
        raise GateFailure("dev.duckdb is not the fresh run's DuckDB leg:\n"
                          + table_text(rep["gates"]["l2_fresh"]["mismatches"]))

    # -- L9
    v = l9_validity(l2_db)
    if v["valid"] and not args.rebuild_l9:
        log(f"L9: reusing target/row_join ({v['why']})")
        head = (LOGS / "l9_build.log").read_text().splitlines() if (LOGS / "l9_build.log").exists() else []
        summ = next((ln for ln in reversed(head) if ln.startswith("Summary:")), "?")
        rep["l9"] = {"build": f"reused; built earlier today, `{summ}`, `logs/rows/l9_build.log`",
                     "validity": "the seven source tables hash identically in dev.duckdb and"
                     " in the copy (every column, parity.metrics_sql), the scratch models/ and"
                     " macros/ equal the tree except the one line, money9 holds"
                     f" {v['money9_relations']} relations", "diff": v["diff"], "check": v}
    else:
        log(f"L9: building ({v['why']})")
        b9 = build_l9(l2_db)
        log(f"  {b9['summary']} (exit {b9['exit']}, {b9['wall_s']} s)")
        if b9["exit"] != 0:
            raise GateFailure(f"L9 build failed: {b9['summary']}")
        rep["l9"] = {"build": f"built by this run, `{b9['summary']}`, {b9['wall_s']} s,"
                     " `logs/rows/l9_build.log`", "validity": "fresh copy", "diff": b9["diff"]}
    db = WORK / "dev.duckdb"
    l9_types = {}
    for r in ddb(db, "SELECT table_name, column_name, data_type FROM information_schema.columns"
                     " WHERE table_schema = 'money9'"):
        l9_types.setdefault(r["table_name"], {})[r["column_name"]] = r["data_type"]
    wrong = [f"{m}.{c}: {l9_types.get(m, {}).get(c)}" for m, c in sorted(money)
             if (m, c) not in FLOAT_COLS and l9_types.get(m, {}).get(c) != "DECIMAL(38,9)"]
    if wrong:
        raise GateFailure("L9 lacks DECIMAL(38,9) where L2 has money_type(): " + "; ".join(wrong))

    # -- pull + transfer proof
    pulls, transfer_bad, n_metrics = {}, [], 0
    for m in models:
        measured, want = rest[m]
        p = pull(bq, db, m, [n for n, _, _ in measured], rels[m])
        got = duck_metrics(db, f"bq_leg.{q(m)}", measured)
        diffs = {k: (want[k], got.get(k)) for k in want if want[k] != got.get(k)}
        n_metrics += len(want)
        p["transfer_proof"] = "equal" if not diffs else diffs
        if diffs:
            transfer_bad.append(m)
        pulls[m] = p
        log(f"  pull {m:34s} {rels[m]:5s} {p['via']:14s} {p['wall_s']:>7.2f} s"
            f" dry-run {p['dry_run_bytes']} B  transfer {'equal' if not diffs else diffs}")
    write_log("pull.log", json.dumps(pulls, indent=1) + "\n")
    rep["gates"]["transfer"] = {
        "ok": not transfer_bad and all(r["ok"] for r in fresh_rows), "models": len(models),
        "metrics": n_metrics, "failed": transfer_bad,
        "fresh_ok": sum(r["ok"] for r in fresh_rows), "fresh_total": len(fresh_rows),
        "fresh_mismatches": [r for r in fresh_rows if not r["ok"]],
        "fresh_unrecorded": sorted(m for m in models if m in fresh["not_measured"])}
    if not rep["gates"]["transfer"]["ok"]:
        write_reports_partial(rep)
        log(f"TRANSFER PROOF FAILED: {transfer_bad}; fresh mismatches"
            f" {rep['gates']['transfer']['fresh_mismatches']}")
        return 1

    # -- join + per column
    rep["models"] = []
    ok_all = True
    for m in models:
        key, others = keys[m][0], keys[m][1:]
        mcols = sorted(c for mm, c in money if mm == m)
        j = join_model(db, l2_db, m, key, others, mcols)
        cols = [column_report(db, l2_db, m, c, key) for c in mcols]
        tot = {b: sum(c[b] for c in cols) for b in ("identical", "A", "B", "C")}
        inv = all(all(c["invariants"].values()) for c in cols)
        ok_all = ok_all and inv and j["ok"]
        entry = {"model": m, "key": key, "other_unique_keys": others, "join": j,
                 "pull": pulls[m], "columns": cols, "totals": tot}
        rep["models"].append(entry)
        write_log(f"{m}.log", json.dumps(entry, indent=1, default=str) + "\n")
        log(f"  join {m:34s} key {key:24s} rows {j['per_leg']['l2']['n']}/{j['per_leg']['l9']['n']}"
            f"/{j['per_leg']['bq']['n']} unmatched {j['unmatched']} join {'ok' if j['ok'] else 'FAIL'}"
            f"  identical {tot['identical']} A {tot['A']} B {tot['B']} C {tot['C']}"
            f"  invariants {'hold' if inv else 'FAIL'}")
        for c in cols:
            if c["C"]:
                log(f"    C {m}.{c['column']}: {c['C']} rows, {c['c_analysis']['verdict']}")

    # -- base control
    rep["base_control"] = base_control(l2_db)
    write_log("base_control.log", json.dumps(rep["base_control"], indent=1) + "\n")
    for b in rep["base_control"]:
        log(f"  base {b['source']:34s} {b['changes']} of {b['n']} change cent  {b['examples']}")

    # -- totals, answer, proposal
    cols = [c for m in rep["models"] for c in m["columns"]]
    tot = {b: sum(c[b] for c in cols) for b in ("rows_compared", "identical", "A", "B", "C",
                                                "cents_differ", "l9_equals_bq", "null_both",
                                                "null_one_side")}
    tot["columns"] = len(cols)
    rep["totals"] = tot
    genuine = [c for c in cols if c["c_analysis"]["verdict"] == "genuinely different"]
    imperfect = [c for c in cols if c["c_analysis"]["verdict"] == "emulation imperfect"]
    g_rows = sum(c["C"] for c in genuine)
    i_rows = sum(c["C"] for c in imperfect)
    name = lambda c: f"`{c['model']}.{c['column']}`"  # noqa: E731
    rep["answer"] = {"genuinely_different_rows": g_rows,
                     "genuinely_different_columns": [name(c) for c in genuine],
                     "emulation_imperfect_rows": i_rows,
                     "emulation_imperfect_columns": [name(c) for c in imperfect]}
    off_buckets = {b: sum(c["l9_not_bq"].get("by_bucket", {}).get(b, 0) for c in cols)
                   for b in ("identical", "A", "B", "C")}
    head = (f"**{g_rows} rows hold genuinely different money** in "
            + ", ".join(f"{name(c)} ({c['C']})" for c in genuine) + "."
            if genuine else
            "**No row holds genuinely different money: 0 unexplained cents.**")
    rep["verdict"] = [
        head, "",
        f"All {len(cols)} money columns of {len(rep['models'])} models ({tot['rows_compared']}"
        f" column-rows) joined on each model's key across L2, L9 and BigQuery: identical"
        f" {tot['identical']}, **A** (same cents, different declared scale) {tot['A']},"
        f" **B** (cents differ; the declared-scale emulation L9 reproduces BigQuery exactly)"
        f" {tot['B']}, **C** (L9 does not reproduce BigQuery) {tot['C']}"
        + (f" - of which emulation imperfect {i_rows} in "
           + ", ".join(f"{name(c)} ({c['C']})" for c in imperfect) if imperfect else "")
        + (f", genuinely different {g_rows}" if genuine else "") + ".",
        "",
        f"L9 equals BigQuery exactly on {tot['l9_equals_bq']} of {tot['rows_compared']}"
        f" column-rows; the {tot['rows_compared'] - tot['l9_equals_bq']} others fall in "
        + ", ".join(f"{b} {n}" for b, n in off_buckets.items() if n)
        + " - the emulation is off there, not the money (see Where L9 is not BigQuery).", "",
        f"NULLs: {tot['null_both']} column-rows are NULL on both legs (counted as identical);"
        f" {tot['null_one_side']} are NULL on one leg only.", "",
        f"Every gate passed: source, rows, transfer. Every join matched every key (0 unmatched,"
        f" 0 NULL, 0 duplicate keys on all three legs); both bucket invariants hold on every"
        f" column.",
        "",
        f"The of-record pair (2026-09-27) cannot be joined row by row any more: the public"
        f" source grew in between (see below)."]
    rep["answer_lines"] = [
        "Is there any row where the money is genuinely different money?",
        "",
        (f"**Yes: {g_rows} rows**, in " + ", ".join(f"{name(c)}" for c in genuine)
         + ". Keys and both values are in the C tables above." if genuine else
         f"**No. 0 rows.** Of {tot['cents_differ']} column-rows whose cents differ, {tot['B']}"
         f" are reproduced exactly by L9 (the declared scale, propagated)"
         + (f", and the other {i_rows} are C rows whose difference is the emulation, not the"
            " money (" + ", ".join(name(c) for c in imperfect) + "; the rule and the"
            " L9 − BQ distribution are with each column)" if imperfect else "") + ".")]
    off = [c for c in cols if c["l9_not_bq"]["rows"]]
    off_n = sum(c["l9_not_bq"]["rows"] for c in off)
    explained = sum(1 for c in off for r in c["l9_not_bq"]["detail"]
                    if r.get("division_rule_explains"))
    rep["l9_off_lines"] = [
        f"All {off_n} rows are `round(x / n, 2)` on a money value and an integer. The inputs are"
        " the same money on L9 and BigQuery, but the engines type the division differently:"
        " DuckDB `DECIMAL / BIGINT` is DOUBLE, so `round(95.6249999995, 2)` = 95.62; BigQuery"
        " `NUMERIC / INT64` is NUMERIC, so the quotient is first rounded to nine decimals"
        " (95.625000000) and then `ROUND(…, 2)` = 95.63. Recomputing both rules on every one of"
        f" these rows reproduces L9 and BigQuery on {explained} of {off_n}"
        " (`division_rule_explains`). L2 equals BigQuery on them because its numerator is"
        " already whole cents (`numerator_l2`), so its DOUBLE quotient is an exact half cent"
        " (`l2_double_quotient`) and rounds away from zero, as BigQuery's does."] if off else []
    rep["proposal"] = [
        "Not applied: `macros/polyglot/types.sql` is unchanged. The one-line change that gives"
        " the DuckDB leg BigQuery's declared scale, exactly as L9 builds it:",
        "", "```diff", rep["l9"]["diff"].rstrip(), "```", "",
        f"What L9 proves about it: with this line, DuckDB's value equals BigQuery's exactly on"
        f" {tot['l9_equals_bq']} of {tot['rows_compared']} compared column-rows, which removes"
        f" all {tot['cents_differ']} cent differences (every one is B)."
        + (f" It is not sufficient on its own: on the other {off_n} rows"
           f" ({', '.join(name(c) for c in off)}) it would *create* a one-cent difference that"
           " the DuckDB leg does not have today (see Where L9 is not BigQuery); closing those"
           " needs the division itself to round to nine decimals before the cents on DuckDB."
           if off else "")
        + " Applying it also changes every published DuckDB money value from 2 to 9 decimals."]
    write_reports(rep)
    log(f"totals {tot}; genuinely different rows {g_rows}; emulation imperfect rows {i_rows}")
    return 0 if ok_all else 1


def write_reports_partial(rep: dict) -> None:
    (VP / "rows.json").write_text(json.dumps(rep, indent=1, default=str) + "\n")


if __name__ == "__main__":
    sys.exit(main())
