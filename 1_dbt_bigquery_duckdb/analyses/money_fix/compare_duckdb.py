"""Row-compare a DuckDB build of this project against project 2's BigQuery build.

The measurement behind the money fix (README.md next to this file). Project 2's BigQuery
leg runs the same SQL as this project's (byte-identical models, the same bigquery__
macros), and it has a credential this project's `coreychimpbot` profile did not. The
rules are project 2's scripts/bq_trino_rows.py, imported, with DuckDB as the source:
every relation is COPYed to Parquet, loaded into BigQuery (a free load job, row-count
gated), FULL OUTER JOINed on its unique key, and every cell classified identical,
equivalent (equal after a stated normalisation) or different.

    BQ_KEYFILE=... BQ_PROJECT=... python compare_duckdb.py <project dir with dev.duckdb> <dataset suffix>

Run it with project 2's .venv (duckdb, google-cloud-bigquery). The project dir is a
build of this project over the real thelook_ecommerce rows; project 2's
target/manifest.json supplies the keys (the models and tests are the same).
"""
import json
import os
import pathlib
import sys

import duckdb
from google.cloud import bigquery

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "2_dbt_bigquery_trino_spark" / "scripts"))
import bq_trino_rows as R  # noqa: E402

variant = pathlib.Path(sys.argv[1]).resolve()
copy_ds = f"trino_experiments_dev_duckdb_{sys.argv[2]}"
project = os.environ["BQ_PROJECT"]
bq = bigquery.Client.from_service_account_json(os.environ["BQ_KEYFILE"], project=project)
bq.create_dataset(bigquery.Dataset(f"{project}.{copy_ds}"), exists_ok=True)
cfg = bigquery.QueryJobConfig(maximum_bytes_billed=5_000_000_000)
keys = R.manifest_keys()

bq_cols = {}
for r in bq.query(f"select table_name, column_name, data_type from `{project}.{R.BQ_DATASET}`."
                  "INFORMATION_SCHEMA.COLUMNS order by table_name, ordinal_position", job_config=cfg).result():
    bq_cols.setdefault(r.table_name, []).append((r.column_name, r.data_type))

con = duckdb.connect(str(variant / "dev.duckdb"), read_only=True)
con.execute("set TimeZone='UTC'")
rels = [r[0] for r in con.execute("select table_name from information_schema.tables "
                                   "where table_schema = 'main' order by 1").fetchall()]
work = variant / "rows"
work.mkdir(exist_ok=True)
out, billed = [], 0
for name in rels:
    dcols = con.execute(f"select column_name, data_type from information_schema.columns where table_schema='main' "
                        f"and table_name='{name}' order by ordinal_position").fetchall()
    path = work / f"{name}.parquet"
    # DuckDB JSON lands in Parquet as bytes; export it as JSON text (what Trino stores, too).
    sel = ", ".join(f'cast("{c}" as varchar) as "{c}"' if t == "JSON" else f'"{c}"' for c, t in dcols)
    con.execute(f"copy (select {sel} from main.\"{name}\") to '{path}' (format parquet)")
    n_src = con.execute(f'select count(*) from main."{name}"').fetchone()[0]
    ref = f"{project}.{copy_ds}.{name}"
    with path.open("rb") as fh:
        bq.load_table_from_file(fh, ref, job_config=bigquery.LoadJobConfig(
            source_format="PARQUET", write_disposition="WRITE_TRUNCATE",
            decimal_target_types=["NUMERIC", "BIGNUMERIC"],
            parquet_options=bigquery.ParquetOptions.from_api_repr({"enableListInference": True}))).result()
    tbl = bq.get_table(ref)
    assert tbl.num_rows == n_src, (name, tbl.num_rows, n_src)
    ctypes = {f.name: (f"ARRAY<{f.field_type}>" if f.mode == "REPEATED" else f.field_type) for f in tbl.schema}
    bmap, key = dict(bq_cols[name]), keys.get(name)
    common = [c for c, _ in dcols if c in bmap]
    aggs, classes = [], {}
    for c in common:
        dtype = dict(dcols)[c]
        if ctypes[c] == "JSON" and bmap[c] == "JSON":
            exact, norm, rule = f"to_json_string(b.`{c}`) = to_json_string(t.`{c}`)", None, "JSON vs JSON"
        else:
            exact, norm, rule = R.compare_exprs(c, bmap[c], ctypes[c], dtype)
        cls = R.class_expr(c, exact, norm)
        classes[c] = (cls, rule, dtype)
        sb = f"b.`{c}`" if bmap[c] == "STRING" else f"to_json_string(b.`{c}`)"
        st = f"t.`{c}`" if ctypes[c] == "STRING" else f"to_json_string(t.`{c}`)"
        aggs.append(f"struct(countif(matched and {cls}='identical') as identical, countif(matched and {cls}='equivalent') as equivalent, "
                    f"countif(matched and {cls}='different') as different, array_agg(if(matched and {cls}='different', "
                    f"struct(to_json_string(k) as key, {sb} as bigquery, {st} as duckdb), null) ignore nulls "
                    f"order by to_json_string(k) limit 3) as examples) as `c_{c}`")
    on = f"b.`{key}` = t.`{key}`" if key else "true"
    kx = f"coalesce(b.`{key}`, t.`{key}`)" if key else "0"
    sql = f"""with b as (select *, true as __present from `{project}.{R.BQ_DATASET}.{name}`),
      t as (select *, true as __present from `{ref}`),
      j as (select b, t, {kx} as k, (b.__present is not null and t.__present is not null) as matched,
                   t.__present is null as only_b, b.__present is null as only_t from b full outer join t on {on})
      select countif(matched) matched, countif(only_b) only_bigquery, countif(only_t) only_duckdb, {", ".join(aggs)} from j"""
    job = bq.query(sql, job_config=cfg)
    row = dict(list(job.result())[0].items())
    billed += job.total_bytes_billed or 0
    cols = [{"column": c, "duckdb_type": classes[c][2], "bigquery_type": bmap[c], "rule": classes[c][1],
             **{k: row[f"c_{c}"][k] for k in ("identical", "equivalent", "different")},
             "examples": [dict(e) for e in row[f"c_{c}"]["examples"]]} for c in common]
    diff = sum(c["different"] for c in cols)
    out.append({"relation": name, "matched": row["matched"], "only_bigquery": row["only_bigquery"],
                "only_duckdb": row["only_duckdb"], "different_cells": diff, "columns": cols})
    print(f"  {'equal' if not diff and not row['only_bigquery'] and not row['only_duckdb'] else 'DIFFERENT':<9} {name:<34} "
          f"{row['matched']:>8} matched  {diff:>8} different cells  only bq/duckdb {row['only_bigquery']}/{row['only_duckdb']}",
          flush=True)
(variant / "rows_report.json").write_text(json.dumps({"variant": variant.name, "bytes_billed": billed, "results": out},
                                                     indent=1, default=str))
cells = sum(r["matched"] * len(r["columns"]) for r in out)
print(f"{variant.name}: {sum(1 for r in out if not r['different_cells'] and not r['only_bigquery'] and not r['only_duckdb'])}"
      f" / {len(out)} relations equal; {sum(r['different_cells'] for r in out):,} of {cells:,} cells different; "
      f"billed {billed / 1e9:.2f} GB")
