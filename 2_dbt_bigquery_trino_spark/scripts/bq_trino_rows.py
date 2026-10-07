"""Row-by-row parity: does every row Trino built equal the row BigQuery built, value for value?

scripts/bq_trino_parity.py compares per-column aggregates. This compares individual rows,
and keeps two questions apart:

  1. VALUE: is each cell the same value on both engines? Every matched row and column
     falls in exactly one class:
       identical   equal as stored, no conversion needed
       equivalent  equal only after a stated normalisation, which is itself a
                   representation difference (e.g. Trino's naive UTC timestamp(6) vs
                   BigQuery's TIMESTAMP instant; JSON compared parsed; a double within
                   1e-12 relative)
       different   not equal (a NULL on one side only counts here too)
     plus rows whose key exists on one engine only, and duplicate keys.
  2. REPRESENTATION: how does each engine type and render the value? Per column: the
     native type on each engine, and on a sample of rows the text each engine renders
     (Trino `cast(x as varchar)` / `json_format`, BigQuery `CAST(x AS STRING)` /
     `TO_JSON_STRING`), so a column whose values agree but whose text differs
     (decimal scale, scientific notation, timestamp suffix) is named.

How the rows meet: every Trino relation is read through the Trino client into Parquet with
types mapped one to one (bigint->int64, decimal(38,9)->decimal128(38,9),
timestamp(6)->timestamp[us] naive, row->struct, array->list), and LOADED into BigQuery
(a load job: free) as <BQ_PROJECT>.trino_experiments_<env>_trino_rows.<relation>. The
loaded row count must equal Trino's (transfer gate). The comparison then runs in BigQuery
SQL as a FULL OUTER JOIN on the model's `unique`-tested key (target/manifest.json).

Writes target/rows/report.md and report.json. Exit 0 every row equal (identical or
equivalent), 1 some cell or key differs, 2 not measurable.

    uv run python scripts/bq_trino_rows.py          # or: make rows
    ROWS_ONLY=fct_orders,dim_users ...              # a subset of relations
"""
from __future__ import annotations

import datetime as dt
import decimal
import json
import os
import pathlib
import re
import sys
import time

import pyarrow as pa
import pyarrow.parquet as pq
import trino
from google.cloud import bigquery

HERE = pathlib.Path(__file__).resolve().parent.parent
WORK = HERE / "target" / "rows"
ENV = os.environ.get("DBT_ENV", "dev")
TRINO_SCHEMA = os.environ.get("ROWS_TRINO_SCHEMA", f"analytics_{ENV}")
BQ_DATASET = f"trino_experiments_{ENV}"
COPY_DATASET = f"trino_experiments_{ENV}_trino_rows"
MAX_BYTES = int(os.environ.get("ROWS_MAXIMUM_BYTES_BILLED", 5_000_000_000))
SAMPLE = int(os.environ.get("ROWS_RENDER_SAMPLE", 200))
EXAMPLES = 5
FLOAT_REL = 1e-12


# ----------------------------------------------------------------- Trino type -> Arrow
def split_top(s: str) -> list[str]:
    parts, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    return parts + [cur.strip()] if cur.strip() else parts


def arrow_type(t: str) -> pa.DataType:
    t = t.strip()
    low = t.lower()
    simple = {"bigint": pa.int64(), "integer": pa.int32(), "smallint": pa.int16(), "tinyint": pa.int8(),
              "double": pa.float64(), "real": pa.float32(), "boolean": pa.bool_(), "date": pa.date32()}
    if low in simple:
        return simple[low]
    if low.startswith(("varchar", "char")):
        return pa.string()
    if m := re.fullmatch(r"decimal\((\d+),\s*(\d+)\)", low):
        return pa.decimal128(int(m[1]), int(m[2]))
    if re.fullmatch(r"timestamp\(\d\) with time zone", low):
        return pa.timestamp("us", tz="UTC")
    if re.fullmatch(r"timestamp\(\d\)", low):
        return pa.timestamp("us")
    if low.startswith("array(") and low.endswith(")"):
        return pa.list_(arrow_type(t[6:-1]))
    if low.startswith("row(") and low.endswith(")"):
        fields = []
        for part in split_top(t[4:-1]):
            m = re.fullmatch(r'"((?:[^"]|"")*)"\s+(.*)', part) or re.fullmatch(r"(\S+)\s+(.*)", part)
            fields.append(pa.field(m[1].replace('""', '"'), arrow_type(m[2])))
        return pa.struct(fields)
    raise ValueError(f"no Arrow mapping for Trino type {t!r}")


def py_value(v, typ: pa.DataType):
    if v is None:
        return None
    if pa.types.is_struct(typ):
        return {f.name: py_value(x, f.type) for f, x in zip(typ, v)}
    if pa.types.is_list(typ):
        return [py_value(x, typ.value_type) for x in v]
    return v


# ------------------------------------------------------------- per-column comparisons
LEGACY = {"INTEGER": "INT64", "FLOAT": "FLOAT64", "BOOLEAN": "BOOL", "RECORD": "STRUCT"}


def compare_exprs(col: str, bq_type: str, copy_type: str, trino_type: str) -> tuple[str | None, str | None, str]:
    """(exact, normalised, rule) for b.col vs t.col; exact is None when no stored-form match exists."""
    b, t = f"b.`{col}`", f"t.`{col}`"
    bt, ct = bq_type.upper(), LEGACY.get(copy_type.upper(), copy_type.upper())
    naive = trino_type.lower().startswith("timestamp") and "with time zone" not in trino_type.lower()
    if bt == "TIMESTAMP" and naive:
        # The load job reads a naive Parquet timestamp as UTC, so `=` here IS the normalisation.
        cmp = f"{b} = timestamp({t}, 'UTC')" if ct == "DATETIME" else f"{b} = {t}"
        return (None, cmp, "BigQuery TIMESTAMP (instant) vs Trino timestamp(6) (naive, UTC by convention)")
    if bt == "FLOAT64":
        return (f"({b} = {t} or (is_nan({b}) and is_nan({t})))",
                f"abs({b} - {t}) <= {FLOAT_REL} * greatest(abs({b}), abs({t}))",
                f"double within {FLOAT_REL:g} relative")
    if bt == "JSON":
        return (f"to_json_string({b}) = {t}",
                f"to_json_string({b}) = to_json_string(parse_json({t}))",
                "BigQuery JSON vs Trino varchar holding JSON text, compared parsed")
    if bt.startswith(("ARRAY", "STRUCT")):
        return (f"to_json_string({b}) = to_json_string({t})", None, "nested, compared element by element")
    if bt == ct or (bt.startswith("NUMERIC") and ct.startswith("NUMERIC")):
        return (f"{b} = {t}", None, "equal as stored")
    return (None, f"cast({b} as string) = cast({t} as string)", f"{bt} vs {ct}, compared as text")


def class_expr(col: str, exact: str | None, norm: str | None) -> str:
    b, t = f"b.`{col}`", f"t.`{col}`"
    nested = exact is not None and exact.startswith("to_json_string(b") and norm is None
    null_test = f"{b} is null and {t} is null" if not nested else "false"
    parts = [f"when {null_test} then 'identical'"]
    if not nested:
        parts.append(f"when {b} is null or {t} is null then 'different'")
    if exact:
        parts.append(f"when {exact} then 'identical'")
    if norm:
        parts.append(f"when {norm} then 'equivalent'")
    return "case " + " ".join(parts) + " else 'different' end"


# ---------------------------------------------------------------------- rendering
def trino_text(col: str, typ: str) -> str:
    c = '"' + col.replace('"', '""') + '"'
    if typ.lower().startswith(("array", "row")):
        return f"json_format(cast({c} as json))"
    return f"cast({c} as varchar)"


def bq_text(col: str, typ: str) -> str:
    c = f"`{col}`"
    if typ.upper().startswith(("ARRAY", "STRUCT", "JSON")):
        return f"to_json_string({c})"
    return f"cast({c} as string)"


def literal(v, engine: str) -> str:
    if isinstance(v, (int, decimal.Decimal)):
        return str(v)
    if isinstance(v, dt.date):
        return f"date '{v.isoformat()}'"
    s = str(v).replace("'", "''") if engine == "trino" else str(v).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{s}'"


# --------------------------------------------------------------------------- main
def manifest_keys() -> dict[str, str]:
    m = json.loads((HERE / "target" / "manifest.json").read_text())
    keys: dict[str, list[str]] = {}
    for n in m["nodes"].values():
        if n["resource_type"] == "test" and n.get("test_metadata", {}).get("name") == "unique":
            keys.setdefault(n["attached_node"].split(".")[-1], []).append(n["test_metadata"]["kwargs"]["column_name"])
    return {k: sorted(v)[0] for k, v in keys.items()}


def main() -> int:
    try:
        tconn = trino.dbapi.connect(host=os.environ.get("TRINO_HOST", "localhost"),
                                    port=int(os.environ.get("TRINO_PORT", 8080)),
                                    user="rows", catalog="lake", timezone="UTC")
        tcur = tconn.cursor()
        tcur.execute("select table_name from information_schema.tables "
                     f"where table_schema = '{TRINO_SCHEMA}' order by table_name")
        trels = [r[0] for r in tcur.fetchall()]
    except Exception as e:  # noqa: BLE001
        print(f"NOT MEASURED: Trino is not reachable ({type(e).__name__}: {e}). make stack-up first.")
        return 2
    try:
        keyfile, project = os.environ.get("BQ_KEYFILE"), os.environ.get("BQ_PROJECT")
        bq = (bigquery.Client.from_service_account_json(keyfile, project=project) if keyfile
              else bigquery.Client(project=project))
        project = bq.project
        bq.create_dataset(bigquery.Dataset(f"{project}.{COPY_DATASET}"), exists_ok=True)
        cfg = bigquery.QueryJobConfig(maximum_bytes_billed=MAX_BYTES)
        bq_cols: dict[str, list[tuple[str, str]]] = {}
        for r in bq.query(f"select table_name, column_name, data_type from `{project}.{BQ_DATASET}`."
                          "INFORMATION_SCHEMA.COLUMNS order by table_name, ordinal_position", job_config=cfg).result():
            bq_cols.setdefault(r.table_name, []).append((r.column_name, r.data_type))
    except Exception as e:  # noqa: BLE001
        print(f"NOT MEASURED: BigQuery is not reachable ({type(e).__name__}: {e}). Set BQ_KEYFILE / BQ_PROJECT.")
        return 2
    try:
        keys = manifest_keys()
    except FileNotFoundError:
        print("NOT MEASURED: target/manifest.json is missing. Run a dbt build first.")
        return 2

    only = {x for x in os.environ.get("ROWS_ONLY", "").split(",") if x}
    names = [n for n in sorted(set(trels) | set(bq_cols)) if not only or n in only]
    WORK.mkdir(parents=True, exist_ok=True)
    results, bytes_billed, failing = [], 0, 0

    for name in names:
        if name not in trels or name not in bq_cols:
            results.append({"relation": name, "status": "MISSING",
                            "detail": "only on " + ("BigQuery" if name in bq_cols else "Trino")})
            failing += 1
            continue
        t0 = time.monotonic()
        tcur.execute("select column_name, data_type from information_schema.columns "
                     f"where table_schema = '{TRINO_SCHEMA}' and table_name = '{name}' order by ordinal_position")
        tcols = tcur.fetchall()
        bmap = dict(bq_cols[name])
        key = keys.get(name)

        # 1. Trino rows -> Parquet -> BigQuery load job (free); gate on the row count.
        schema = pa.schema([pa.field(c, arrow_type(t)) for c, t in tcols])
        sel = ", ".join('"' + c.replace('"', '""') + '"' for c, _ in tcols)
        tcur.execute(f'select {sel} from lake."{TRINO_SCHEMA}"."{name}"')
        path = WORK / f"{name}.parquet"
        n_trino = 0
        with pq.ParquetWriter(path, schema) as writer:
            while batch := tcur.fetchmany(100_000):
                cols = list(zip(*batch))
                writer.write_table(pa.table([pa.array([py_value(v, f.type) for v in col], type=f.type)
                                             for col, f in zip(cols, schema)], schema=schema))
                n_trino += len(batch)
        load_cfg = bigquery.LoadJobConfig(source_format=bigquery.SourceFormat.PARQUET,
                                          write_disposition="WRITE_TRUNCATE",
                                          decimal_target_types=["NUMERIC", "BIGNUMERIC"],
                                          parquet_options=bigquery.ParquetOptions.from_api_repr(
                                              {"enableListInference": True}))
        copy_ref = f"{project}.{COPY_DATASET}.{name}"
        with path.open("rb") as fh:
            bq.load_table_from_file(fh, copy_ref, job_config=load_cfg).result()
        copy_table = bq.get_table(copy_ref)
        copy_types = {f.name: (f"ARRAY<{f.field_type}>" if f.mode == "REPEATED" else f.field_type)
                      for f in copy_table.schema}
        transfer_s = time.monotonic() - t0
        if copy_table.num_rows != n_trino:
            results.append({"relation": name, "status": "NOT MEASURED",
                            "detail": f"transfer gate: Trino {n_trino} rows, loaded {copy_table.num_rows}"})
            failing += 1
            continue

        # 2. FULL OUTER JOIN on the key, every column classified on every matched row.
        common = [c for c, _ in tcols if c in bmap]
        name_diff = [c for c, _ in tcols if c not in bmap] + [c for c in bmap if c not in dict(tcols)]
        rules, aggs = {}, []
        for c in common:
            exact, norm, rule = compare_exprs(c, bmap[c], copy_types[c], dict(tcols)[c])
            rules[c] = rule
            cls = class_expr(c, exact, norm)
            show_b = f"b.`{c}`" if bmap[c].upper() == "STRING" else f"to_json_string(b.`{c}`)"
            show_t = f"t.`{c}`" if copy_types[c].upper() == "STRING" else f"to_json_string(t.`{c}`)"
            ex = (f"array_agg(if(matched and {cls} != 'identical', struct({cls} as class, "
                  f"to_json_string(k) as key, {show_b} as bigquery, {show_t} as trino), "
                  f"null) ignore nulls order by {cls} = 'different' desc, to_json_string(k) limit {EXAMPLES})")
            aggs.append(f"struct(countif(matched and {cls} = 'identical') as identical, "
                        f"countif(matched and {cls} = 'equivalent') as equivalent, "
                        f"countif(matched and {cls} = 'different') as different, {ex} as examples) as `c_{c}`")
        all_classes = [class_expr(c, *compare_exprs(c, bmap[c], copy_types[c], dict(tcols)[c])[:2]) for c in common]
        row_ident = " and ".join(f"{x} = 'identical'" for x in all_classes) or "true"
        row_equal = " and ".join(f"{x} != 'different'" for x in all_classes) or "true"
        join_on = f"b.`{key}` = t.`{key}`" if key else "true"
        key_expr = f"coalesce(b.`{key}`, t.`{key}`)" if key else "0"
        sql = f"""
with b as (select *, true as __present from `{project}.{BQ_DATASET}.{name}`),
     t as (select *, true as __present from `{copy_ref}`),
     -- A missing side of an outer join is a struct of NULLs here, not NULL: test __present.
     j as (select b, t, {key_expr} as k, (b.__present is not null and t.__present is not null) as matched,
                  b.__present is null as only_t, t.__present is null as only_b
           from b full outer join t on {join_on})
select count(*) as joined, countif(matched) as matched,
       countif(only_b) as only_bigquery, countif(only_t) as only_trino,
       (select count(*) - count(distinct {f'`{key}`' if key else '0'}) from b) as dup_keys_bigquery,
       (select count(*) - count(distinct {f'`{key}`' if key else '0'}) from t) as dup_keys_trino,
       countif(matched and {row_ident}) as rows_identical,
       countif(matched and {row_equal}) as rows_equal,
       array_agg(if(not matched, struct(to_json_string(k) as key, if(only_t, 'trino', 'bigquery') as side), null)
                 ignore nulls order by to_json_string(k) limit {EXAMPLES}) as unmatched_examples,
       {", ".join(aggs)}
from j
"""
        job = bq.query(sql, job_config=cfg)
        row = dict(list(job.result())[0].items())
        bytes_billed += job.total_bytes_billed or 0

        # 3. Rendering on a sample of keys: the text each engine produces for the same value.
        render = {}
        if key:
            tcur.execute(f'select "{key}" from lake."{TRINO_SCHEMA}"."{name}" order by 1 limit {SAMPLE}')
            sample = [r[0] for r in tcur.fetchall()]
            tcur.execute(f'select "{key}", {", ".join(trino_text(c, dict(tcols)[c]) for c in common)} '
                         f'from lake."{TRINO_SCHEMA}"."{name}" '
                         f'where "{key}" in ({", ".join(literal(v, "trino") for v in sample)})')
            ttext = {str(r[0]): r[1:] for r in tcur.fetchall()}
            bjob = bq.query(f"select cast(`{key}` as string) as k, {', '.join(bq_text(c, bmap[c]) for c in common)} "
                            f"from `{project}.{BQ_DATASET}.{name}` "
                            f"where `{key}` in ({', '.join(literal(v, 'bq') for v in sample)})", job_config=cfg)
            btext = {r[0]: tuple(r)[1:] for r in bjob.result()}
            bytes_billed += bjob.total_bytes_billed or 0
            for i, c in enumerate(common):
                pairs = [(btext[k][i], ttext[k][i]) for k in btext if k in ttext]
                diff = [p for p in pairs if p[0] != p[1]]
                render[c] = {"sampled": len(pairs), "text_differs": len(diff), "example": list(diff[0]) if diff else None}
        else:
            tcur.execute(f'select {", ".join(trino_text(c, dict(tcols)[c]) for c in common)} '
                         f'from lake."{TRINO_SCHEMA}"."{name}" limit 1')
            tt = tcur.fetchone()
            bt = tuple(list(bq.query(f"select {', '.join(bq_text(c, bmap[c]) for c in common)} "
                                     f"from `{project}.{BQ_DATASET}.{name}` limit 1", job_config=cfg).result())[0])
            for i, c in enumerate(common):
                render[c] = {"sampled": 1, "text_differs": int(bt[i] != tt[i]),
                             "example": [bt[i], tt[i]] if bt[i] != tt[i] else None}

        columns = []
        for c in common:
            agg = row[f"c_{c}"]
            columns.append({"column": c, "trino_type": dict(tcols)[c], "bigquery_type": bmap[c],
                            "loaded_as": copy_types[c], "rule": rules[c],
                            "identical": agg["identical"], "equivalent": agg["equivalent"],
                            "different": agg["different"], "examples": [dict(e) for e in agg["examples"]],
                            "render": render.get(c)})
        bad = (row["only_bigquery"] or row["only_trino"] or row["dup_keys_bigquery"] or row["dup_keys_trino"]
               or any(c["different"] for c in columns) or name_diff)
        failing += bool(bad)
        results.append({"relation": name, "key": key, "status": "DIFFERENT" if bad else "equal",
                        "rows_trino": n_trino, "joined": row["joined"], "matched": row["matched"],
                        "only_bigquery": row["only_bigquery"], "only_trino": row["only_trino"],
                        "dup_keys_bigquery": row["dup_keys_bigquery"], "dup_keys_trino": row["dup_keys_trino"],
                        "rows_identical": row["rows_identical"], "rows_equal": row["rows_equal"],
                        "unmatched_examples": [dict(e) for e in row["unmatched_examples"]],
                        "name_differences": name_diff, "columns": columns,
                        "seconds": round(time.monotonic() - t0, 1), "transfer_seconds": round(transfer_s, 1)})
        r = results[-1]
        print(f"  {r['status']:<9} {name:<34} {r['matched']:>8} matched  {r['rows_identical']:>8} identical  "
              f"{r['rows_equal']:>8} equal  only bq/trino {r['only_bigquery']}/{r['only_trino']}  {r['seconds']}s",
              flush=True)

    write_reports(results, project, bytes_billed)
    return 0 if failing == 0 else 1


def write_reports(results: list, project: str, bytes_billed: int) -> None:
    (WORK / "report.json").write_text(json.dumps(
        {"trino": f"lake.{TRINO_SCHEMA}", "bigquery": f"{project}.{BQ_DATASET}",
         "trino_copy_in_bigquery": f"{project}.{COPY_DATASET}", "bytes_billed": bytes_billed,
         "results": results}, indent=1, default=str))
    ok = [r for r in results if "columns" in r]
    cells = sum(r["matched"] * len(r["columns"]) for r in ok)
    ident = sum(c["identical"] for r in ok for c in r["columns"])
    equiv = sum(c["equivalent"] for r in ok for c in r["columns"])
    diff = sum(c["different"] for r in ok for c in r["columns"])
    L = [f"# Row-level parity: lake.{TRINO_SCHEMA} (Trino) vs {project}.{BQ_DATASET} (BigQuery)", "",
         f"**{sum(r['status'] == 'equal' for r in results)} / {len(results)} relations equal row for row.** "
         f"{sum(r['matched'] for r in ok):,} rows matched on their key; {cells:,} cells compared: "
         f"{ident:,} identical, {equiv:,} equivalent (equal after a stated normalisation), {diff:,} different. "
         f"Rows on one engine only: {sum(r['only_bigquery'] + r['only_trino'] for r in ok)}. "
         f"BigQuery billed {bytes_billed / 1e9:.2f} GB.", "",
         "## Per relation", "",
         "| relation | key | status | rows matched | rows identical | rows equal | only BQ / only Trino | dup keys BQ / Trino |",
         "|---|---|---|---:|---:|---:|---:|---:|"]
    for r in results:
        if "columns" not in r:
            L.append(f"| `{r['relation']}` | | {r['status']} | | | | {r.get('detail', '')} | |")
            continue
        L.append(f"| `{r['relation']}` | `{r['key'] or '(single row)'}` | {r['status']} | {r['matched']:,} | "
                 f"{r['rows_identical']:,} | {r['rows_equal']:,} | {r['only_bigquery']} / {r['only_trino']} | "
                 f"{r['dup_keys_bigquery']} / {r['dup_keys_trino']} |")

    L += ["", "## Columns whose values needed a normalisation, or differ", "",
          "Each is a representation difference (when every row is `equivalent`) or a value difference "
          "(any `different`).", "",
          "| relation.column | Trino type | BigQuery type | rule | identical | equivalent | different | example (BQ / Trino) |",
          "|---|---|---|---|---:|---:|---:|---|"]
    for r in ok:
        for c in r["columns"]:
            if c["equivalent"] or c["different"]:
                e = c["examples"][0] if c["examples"] else None
                ex = f"`{e['bigquery']}` / `{e['trino']}`" if e else ""
                L.append(f"| `{r['relation']}.{c['column']}` | `{c['trino_type']}` | `{c['bigquery_type']}` | {c['rule']} "
                         f"| {c['identical']:,} | {c['equivalent']:,} | {c['different']:,} | {ex.replace('|', '/')} |")

    L += ["", "## Representation: same value, different type or text", "",
          "Grouped by the pair of native types. *Text* is what each engine renders for the same cell "
          "(Trino `cast(x as varchar)` / `json_format`, BigQuery `CAST(x AS STRING)` / `TO_JSON_STRING`), "
          f"on a sample of up to {SAMPLE} keys per relation.", "",
          "| Trino type | BigQuery type | columns | values | text differs (sampled cells) | example text (BQ / Trino) |",
          "|---|---|---:|---|---:|---|"]
    groups: dict = {}
    for r in ok:
        for c in r["columns"]:
            tt = re.sub(r'"[^"]*"', "…", c["trino_type"]) if c["trino_type"].startswith("row") else c["trino_type"]
            g = groups.setdefault((tt, c["bigquery_type"] if not c["bigquery_type"].startswith("STRUCT") else "STRUCT<…>"),
                                  {"n": 0, "ident": 0, "equiv": 0, "diff": 0, "sampled": 0, "tdiff": 0, "ex": None})
            g["n"] += 1
            g["ident"] += c["identical"]
            g["equiv"] += c["equivalent"]
            g["diff"] += c["different"]
            if c["render"]:
                g["sampled"] += c["render"]["sampled"]
                g["tdiff"] += c["render"]["text_differs"]
                g["ex"] = g["ex"] or c["render"]["example"]
    for (tt, bt), g in sorted(groups.items()):
        values = ("identical" if not (g["equiv"] or g["diff"]) else
                  f"{g['diff']:,} different" if g["diff"] else "equivalent (normalised)")
        ex = f"`{g['ex'][0]}` / `{g['ex'][1]}`" if g["ex"] else ""
        L.append(f"| `{tt}` | `{bt}` | {g['n']} | {values} | {g['tdiff']:,} / {g['sampled']:,} | {ex.replace('|', '/')} |")
    (WORK / "report.md").write_text("\n".join(L) + "\n")
    print("\n" + "\n".join(L))


if __name__ == "__main__":
    sys.exit(main())
