"""Value parity: does the Trino leg build the same data as the BigQuery leg?

Meaningful only when both legs read the SAME rows: the BigQuery build reads
bigquery-public-data.thelook_ecommerce, so the Trino leg must have been built on the
real rows too (make land-real && dbt build --target trino), not the fixture.

For every relation dbt built on both targets (BigQuery <BQ_PROJECT>.trino_experiments_<env>,
Trino lake.analytics_<env>) it computes, on each engine, the same profile as
scripts/spark_interop.py: row count, then per column a non-null count and, by kind, an
exact sum (integers, decimals), a sum (doubles, 1e-9 relative), a distinct count and total
length (text), distinct/min/max (dates), distinct and min/max epoch MICROSECONDS
(timestamps), total cardinality (arrays). Column names are compared too.

Two conversions are applied on BigQuery so a column means the same text on both sides:
GEOGRAPHY is profiled as ST_ASTEXT (Trino stores WKT varchar) and JSON as
TO_JSON_STRING (Trino stores json_format(...) varchar). Their text may still differ
(WKT number formatting, JSON key order), which the report shows rather than hides.

Writes target/parity/report.md and report.json. Exit 0 every relation identical, 1 some
relation differs, 2 one leg not measurable.

    uv run python scripts/bq_trino_parity.py      # or: make parity
"""
from __future__ import annotations

import decimal
import json
import math
import os
import pathlib
import sys
import time

import trino
from google.cloud import bigquery

HERE = pathlib.Path(__file__).resolve().parent.parent
REPORT = HERE / "target" / "parity"
ENV = os.environ.get("DBT_ENV", "dev")
TRINO_SCHEMA = f"analytics_{ENV}"
BQ_DATASET = f"trino_experiments_{ENV}"
MAX_BYTES = int(os.environ.get("BQ_MAXIMUM_BYTES_BILLED", 1_000_000_000))


def trino_kind(t: str) -> str:
    t = t.lower()
    if t.startswith(("bigint", "integer", "smallint", "tinyint", "decimal")):
        return "num"
    if t in ("double", "real"):
        return "dbl"
    if t.startswith(("varchar", "char")):
        return "str"
    if t == "boolean":
        return "bool"
    if t == "date":
        return "date"
    if t.startswith("timestamp"):
        return "ts"
    if t.startswith("array"):
        return "array"
    return "row"


def bq_kind(t: str) -> str:
    t = t.upper()
    if t in ("INT64", "NUMERIC", "BIGNUMERIC") or t.startswith(("NUMERIC(", "BIGNUMERIC(")):
        return "num"
    if t == "FLOAT64":
        return "dbl"
    if t in ("STRING", "GEOGRAPHY", "JSON"):
        return "str"
    if t == "BOOL":
        return "bool"
    if t == "DATE":
        return "date"
    if t in ("TIMESTAMP", "DATETIME"):
        return "ts"
    if t.startswith("ARRAY"):
        return "array"
    return "row"


METRICS = {"num": ["count", "sum"], "dbl": ["count", "sum"], "str": ["count", "distinct", "length"],
           "bool": ["count", "true"], "date": ["count", "distinct", "min", "max"],
           "ts": ["count", "distinct", "min_us", "max_us"], "array": ["count", "elements"], "row": ["count"]}


def trino_exprs(col: str, kind: str, typ: str) -> list[str]:
    c = '"' + col.replace('"', '""') + '"'
    if kind == "num":
        return [f"count({c})", f"cast(sum({c}) as varchar)"]
    if kind == "dbl":
        return [f"count({c})", f"sum({c})"]
    if kind == "str":
        return [f"count({c})", f"count(distinct {c})", f"sum(length({c}))"]
    if kind == "bool":
        return [f"count({c})", f"count_if({c})"]
    if kind == "date":
        return [f"count({c})", f"count(distinct {c})", f"cast(min({c}) as varchar)", f"cast(max({c}) as varchar)"]
    if kind == "ts":
        instant = c if "with time zone" in typ else f"with_timezone({c}, 'UTC')"
        micros = f"cast(round(to_unixtime({instant}) * 1000000) as bigint)"
        return [f"count({c})", f"count(distinct {c})", f"min({micros})", f"max({micros})"]
    if kind == "array":
        return [f"count({c})", f"sum(cardinality({c}))"]
    return [f"count({c})"]


def bq_exprs(col: str, kind: str, typ: str) -> list[str]:
    raw = f"`{col}`"
    t = typ.upper()
    c = f"ST_ASTEXT({raw})" if t == "GEOGRAPHY" else f"TO_JSON_STRING({raw})" if t == "JSON" else raw
    if kind == "num":
        return [f"count({c})", f"cast(sum({c}) as string)"]
    if kind == "dbl":
        return [f"count({c})", f"sum({c})"]
    if kind == "str":
        return [f"count({c})", f"count(distinct {c})", f"sum(length({c}))"]
    if kind == "bool":
        return [f"count({c})", f"countif({c})"]
    if kind == "date":
        return [f"count({c})", f"count(distinct {c})", f"cast(min({c}) as string)", f"cast(max({c}) as string)"]
    if kind == "ts":
        micros = f"unix_micros({c})" if t == "TIMESTAMP" else f"unix_micros(timestamp({c}))"
        return [f"count({c})", f"count(distinct {c})", f"min({micros})", f"max({micros})"]
    if kind == "array":
        # BigQuery has no NULL arrays (NULL becomes []), so count() counts every row.
        return [f"count({c})", f"sum(array_length({c}))"]
    return [f"count({c})"]


def norm(v):
    if v is None:
        return None
    return float(v) if isinstance(v, float) else str(v)


def same(a, b, metric_kind: str):
    """(equal?, relative difference or None)."""
    if a is None or b is None:
        return (a is None and b is None), None
    if metric_kind == "dbl":
        x, y = float(a), float(b)
        rel = abs(x - y) / max(abs(x), abs(y), 1e-300)
        return math.isclose(x, y, rel_tol=1e-9, abs_tol=1e-9), rel
    try:
        x, y = decimal.Decimal(str(a)), decimal.Decimal(str(b))
        rel = float(abs(x - y) / max(abs(x), abs(y))) if max(abs(x), abs(y)) else 0.0
        return x == y, rel
    except decimal.InvalidOperation:
        return str(a) == str(b), None


def main() -> int:
    try:
        tconn = trino.dbapi.connect(host=os.environ.get("TRINO_HOST", "localhost"),
                                    port=int(os.environ.get("TRINO_PORT", 8080)),
                                    user="parity", catalog="lake", timezone="UTC")
        tcur = tconn.cursor()
        tcur.execute("select table_name, table_type from information_schema.tables "
                     f"where table_schema = '{TRINO_SCHEMA}' order by table_name")
        trels = dict(tcur.fetchall())
    except Exception as e:  # noqa: BLE001
        print(f"NOT MEASURED: Trino is not reachable ({type(e).__name__}: {e}). make stack-up first.")
        return 2
    try:
        project = os.environ.get("BQ_PROJECT")
        keyfile = os.environ.get("BQ_KEYFILE")
        bq = (bigquery.Client.from_service_account_json(keyfile, project=project) if keyfile
              else bigquery.Client(project=project))
        project = bq.project
        cfg = bigquery.QueryJobConfig(maximum_bytes_billed=MAX_BYTES, use_legacy_sql=False)
        rows = bq.query(f"select table_name, column_name, data_type from `{project}.{BQ_DATASET}`."
                        "INFORMATION_SCHEMA.COLUMNS order by table_name, ordinal_position", job_config=cfg).result()
        bq_cols: dict[str, list[tuple[str, str]]] = {}
        for r in rows:
            bq_cols.setdefault(r.table_name, []).append((r.column_name, r.data_type))
    except Exception as e:  # noqa: BLE001
        print(f"NOT MEASURED: BigQuery is not reachable ({type(e).__name__}: {e}). Set BQ_KEYFILE / BQ_PROJECT.")
        return 2

    names = sorted(set(trels) | set(bq_cols))
    results, bytes_billed, differing = [], 0, 0
    for name in names:
        if name not in trels or name not in bq_cols:
            results.append({"relation": name, "status": "MISSING",
                            "detail": "only on " + ("BigQuery" if name in bq_cols else "Trino")})
            differing += 1
            continue
        tcur.execute("select column_name, data_type from information_schema.columns "
                     f"where table_schema = '{TRINO_SCHEMA}' and table_name = '{name}' order by ordinal_position")
        tcols = tcur.fetchall()
        bcols = bq_cols[name]
        tmap, bmap = dict(tcols), dict(bcols)
        name_diff = [c for c, _ in tcols if c not in bmap] + [c for c, _ in bcols if c not in tmap]

        labels, kinds, texprs, bexprs, kind_diff = ["rows"], ["num"], ["count(*)"], ["count(*)"], []
        for col, ttype in tcols:
            if col not in bmap:
                continue
            tk, bk = trino_kind(ttype), bq_kind(bmap[col])
            k = tk if tk == bk else "row"  # different kinds: compare the non-null count only
            if tk != bk:
                kind_diff.append(f"{col}: {ttype} vs {bmap[col]}")
            labels += [f"{col}.{m}" for m in METRICS[k]]
            kinds += ["dbl" if (k == "dbl" and m == "sum") else "num" if m != "min" and m != "max" else k
                      for m in METRICS[k]]
            texprs += trino_exprs(col, k, ttype)
            bexprs += bq_exprs(col, k, bmap[col])

        t0 = time.monotonic()
        tcur.execute(f'select {", ".join(texprs)} from lake."{TRINO_SCHEMA}"."{name}"')
        tvals = [norm(v) for v in tcur.fetchone()]
        t_secs = time.monotonic() - t0
        t0 = time.monotonic()
        job = bq.query(f"select {', '.join(bexprs)} from `{project}.{BQ_DATASET}.{name}`", job_config=cfg)
        bvals = [norm(v) for v in list(job.result())[0].values()]
        b_secs = time.monotonic() - t0
        bytes_billed += job.total_bytes_billed or 0

        diffs = []
        for lab, k, a, b in zip(labels, kinds, tvals, bvals):
            ok, rel = same(a, b, k)
            if not ok:
                diffs.append({"metric": lab, "trino": a, "bigquery": b, "rel_diff": rel})
        status = "identical" if not (diffs or name_diff or kind_diff) else "DIFFERENT"
        differing += status != "identical"
        results.append({"relation": name, "type": "table" if trels[name] == "BASE TABLE" else "view",
                        "status": status, "rows_trino": tvals[0], "rows_bigquery": bvals[0],
                        "columns": len(tcols), "metrics": len(labels), "name_differences": name_diff,
                        "kind_differences": kind_diff, "differences": diffs,
                        "trino_types": tmap, "bigquery_types": bmap,
                        "profile_seconds": {"trino": round(t_secs, 2), "bigquery": round(b_secs, 2)}})

    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / "report.json").write_text(json.dumps(
        {"trino": f"lake.{TRINO_SCHEMA}", "bigquery": f"{project}.{BQ_DATASET}",
         "bytes_billed_by_profiling": bytes_billed, "results": results}, indent=1, default=str))

    lines = [f"# BigQuery vs Trino: lake.{TRINO_SCHEMA} against {project}.{BQ_DATASET}", "",
             "A relation is `identical` when its column names match and every column's profile "
             "(non-null counts, exact sums, double sums to 1e-9, distinct counts, text lengths, "
             "date and timestamp ranges in epoch microseconds, array sizes) is equal on both engines.", "",
             "| relation | type | status | rows (Trino / BQ) | differing metrics |", "|---|---|---|---:|---|"]
    for r in results:
        if r["status"] == "MISSING":
            lines.append(f"| `{r['relation']}` | | MISSING | | {r['detail']} |")
            continue
        detail = [f"{d['metric']}" for d in r["differences"]] + [f"name: {n}" for n in r["name_differences"]] \
            + [f"kind: {k}" for k in r["kind_differences"]]
        shown = ", ".join(detail[:5]) + (f" (+{len(detail) - 5} more)" if len(detail) > 5 else "")
        lines.append(f"| `{r['relation']}` | {r['type']} | {r['status']} | {r['rows_trino']} / {r['rows_bigquery']} "
                     f"| {len(r['differences'])}/{r['metrics']}{': ' + shown if shown else ''} |")
    same_n = sum(r["status"] == "identical" for r in results)
    lines += ["", f"Summary: {same_n} / {len(results)} relations identical; profiling billed "
              f"{bytes_billed / 1e6:.1f} MB on BigQuery."]
    (REPORT / "report.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[4:]))
    return 0 if differing == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
