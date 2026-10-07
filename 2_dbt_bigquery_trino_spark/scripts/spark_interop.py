"""Prove that Spark reads what dbt built on Trino, and sees the same data.

For every relation in the dbt schema (default lake.analytics_${DBT_ENV:-dev}):
  1. profile each column in Trino SQL: row count, then per column a count and, by kind,
     an exact sum (integers, decimals), a sum (doubles, compared to 1e-9 relative),
     a distinct count and total length (text), min/max (dates), distinct count and
     min/max epoch MICROSECONDS (timestamps), total cardinality (arrays);
  2. run the Spark job stack/spark/jobs/profile_relations.py, which computes the same
     profile in Spark SQL through Spark's own Iceberg reader;
  3. compare, column by column.

Gate (exit 1): every TABLE must be readable by Spark and profile-identical. Tables are
the contract with Spark (dbt_project.yml: marts are tables). VIEWS are reported, never
gated: a Trino view is stored as Trino SQL, so Spark either cannot read it, or reads it
by RE-EXECUTING that SQL with Spark semantics, which is the case to fear (it can return
different data without an error). The report says which views fall in which bucket.
Exit 2: the stack is not reachable (nothing was measured).

Writes target/interop/report.md and report.json.

    uv run python scripts/spark_interop.py         # or: make interop
"""
from __future__ import annotations

import decimal
import json
import math
import os
import pathlib
import subprocess
import sys

import trino

HERE = pathlib.Path(__file__).resolve().parent.parent
IO = HERE / "target" / "stack_io" / "interop"
REPORT = HERE / "target" / "interop"
SCHEMA = os.environ.get("INTEROP_SCHEMA", f"analytics_{os.environ.get('DBT_ENV', 'dev')}")


def kind_of(trino_type: str) -> str:
    t = trino_type.lower()
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


def trino_exprs(col: str, kind: str, trino_type: str) -> list[str]:
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
        instant = c if "with time zone" in trino_type else f"with_timezone({c}, 'UTC')"
        micros = f"cast(round(to_unixtime({instant}) * 1000000) as bigint)"
        return [f"count({c})", f"count(distinct {c})", f"min({micros})", f"max({micros})"]
    if kind == "array":
        return [f"count({c})", f"sum(cardinality({c}))"]
    return [f"count({c})"]


def labels(col: str, kind: str) -> list[str]:
    names = {"num": ["count", "sum"], "dbl": ["count", "sum"], "str": ["count", "distinct", "length"],
             "bool": ["count", "true"], "date": ["count", "distinct", "min", "max"],
             "ts": ["count", "distinct", "min_us", "max_us"], "array": ["count", "elements"]}
    return [f"{col}.{m}" for m in names.get(kind, ["count"])]


def same(a, b, kind: str) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if kind == "dbl":
        x, y = float(a), float(b)
        return math.isclose(x, y, rel_tol=1e-9, abs_tol=1e-9)
    try:
        return decimal.Decimal(str(a)) == decimal.Decimal(str(b))
    except decimal.InvalidOperation:
        return str(a) == str(b)


def main() -> int:
    try:
        conn = trino.dbapi.connect(host=os.environ.get("TRINO_HOST", "localhost"),
                                   port=int(os.environ.get("TRINO_PORT", 8080)),
                                   user="interop", catalog="lake", timezone="UTC")
        cur = conn.cursor()
        cur.execute("select table_name, table_type from information_schema.tables "
                    f"where table_schema = '{SCHEMA}' order by table_name")
        rels = cur.fetchall()
    except Exception as e:  # noqa: BLE001
        print(f"NOT MEASURED: Trino is not reachable ({type(e).__name__}: {e}). make stack-up first.")
        return 2
    if not rels:
        print(f"NOT MEASURED: lake.{SCHEMA} holds no relations. Run the dbt build first.")
        return 2

    spec = {"schema": SCHEMA, "relations": []}
    trino_profiles: dict[str, dict] = {}
    for name, rtype in rels:
        cur.execute("select column_name, data_type from information_schema.columns "
                    f"where table_schema = '{SCHEMA}' and table_name = '{name}' order by ordinal_position")
        cols = [{"name": c, "type": t, "kind": kind_of(t)} for c, t in cur.fetchall()]
        select = ["count(*)"]
        names = ["rows"]
        for col in cols:
            select += trino_exprs(col["name"], col["kind"], col["type"])
            names += labels(col["name"], col["kind"])
        cur.execute(f'select {", ".join(select)} from lake."{SCHEMA}"."{name}"')
        values = [None if v is None else (float(v) if isinstance(v, float) else str(v)) for v in cur.fetchone()]
        trino_profiles[name] = {"type": "table" if rtype == "BASE TABLE" else "view",
                                "columns": cols, "labels": names, "values": values}
        spec["relations"].append({"name": name, "columns": [{"name": c["name"], "kind": c["kind"]} for c in cols]})

    IO.mkdir(parents=True, exist_ok=True)
    (IO / "spec.json").write_text(json.dumps(spec, indent=1))
    (IO / "spark.json").unlink(missing_ok=True)
    print(f"profiled {len(rels)} relations of lake.{SCHEMA} on Trino; running the Spark reader ...")
    run = subprocess.run(["docker", "compose", "-f", str(HERE / "stack" / "compose.yml"), "run", "--rm", "-T",
                          "spark", "profile_relations.py"], capture_output=True, text=True)
    if not (IO / "spark.json").is_file():
        print(run.stdout[-3000:], run.stderr[-3000:], sep="\n")
        print("NOT MEASURED: the Spark job wrote no result.")
        return 2
    spark = json.loads((IO / "spark.json").read_text())

    results, failures = [], 0
    for name, tp in trino_profiles.items():
        sp = spark["relations"].get(name, {"ok": False, "error": "not profiled"})
        kinds = ["num"] + [k for c in tp["columns"] for k in [c["kind"]] * len(labels(c["name"], c["kind"]))]
        if not sp["ok"]:
            status = "unreadable"
            diffs = []
        else:
            diffs = [lab for lab, k, a, b in zip(tp["labels"], kinds, tp["values"], sp["values"]) if not same(a, b, k)]
            status = "identical" if not diffs else "DIFFERENT"
        gated = tp["type"] == "table" and status != "identical"
        failures += gated
        results.append({"relation": name, "type": tp["type"], "status": status, "gated_failure": gated,
                        "differences": diffs, "error": sp.get("error"), "rows": tp["values"][0],
                        "trino_types": {c["name"]: c["type"] for c in tp["columns"]},
                        "spark_schema": sp.get("spark_schema")})

    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / "report.json").write_text(json.dumps({"schema": SCHEMA, "spark_version": spark["spark_version"],
                                                    "results": results}, indent=1))
    lines = [f"# Spark reads what dbt built on Trino (lake.{SCHEMA})", "",
             f"Spark {spark['spark_version']} through the shared Iceberg REST catalog. A relation is "
             "`identical` when every column's profile (counts, exact sums, distinct counts, "
             "timestamp ranges in epoch microseconds, array sizes) is equal on both engines.", "",
             "| relation | Trino type | Spark | rows | detail |", "|---|---|---|---:|---|"]
    for r in results:
        detail = r["error"] or (", ".join(r["differences"][:6]) if r["differences"] else "")
        lines.append(f"| `{r['relation']}` | {r['type']} | {r['status']} | {r['rows']} | {detail.replace('|', '/')} |")
    counts = {}
    for r in results:
        counts[(r["type"], r["status"])] = counts.get((r["type"], r["status"]), 0) + 1
    summary = ", ".join(f"{n} {t}s {s}" for (t, s), n in sorted(counts.items()))
    lines += ["", f"Summary: {summary}."]
    (REPORT / "report.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines[4:]))
    if failures:
        print(f"\ninterop: FAILED: {failures} table(s) unreadable by Spark or different on Spark")
        return 1
    print(f"\ninterop: every table dbt built on Trino is read by Spark with an identical profile ({summary})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
