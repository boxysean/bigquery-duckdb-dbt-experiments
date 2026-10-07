"""Probe: can the community extension read a BigQuery VIEW, and how?

    BQ_KEYFILE=... DBT_ENV=rows python3 analyses/value_parity/probes/scan_view.py

scripts/row_join.py pulls the BigQuery leg into DuckDB. The staging and intermediate
models are views on BigQuery; this shows bigquery_scan (Storage Read API) refusing one
and bigquery_query (a query job) reading it, with the type NUMERIC arrives as - and that
an aggregate directly over bigquery_query(use_rest_api) hits an INTERNAL error, while a
projection, or materialising first (row_join.py's shape), works.
Writes nothing (in-memory DuckDB).
"""
import os
import shutil
import subprocess

KEY = os.environ["BQ_KEYFILE"]
REL = f"coreychimpbot.experiments_{os.environ.get('DBT_ENV', 'dev')}"
PRE = ("LOAD bigquery;\n"
       f"CREATE TEMPORARY SECRET s (TYPE bigquery, SCOPE 'bq://coreychimpbot',"
       f" SERVICE_ACCOUNT_PATH '{KEY}');\n")
TRIES = [
    ("bigquery_scan on a VIEW",
     f"SELECT count(*) FROM bigquery_scan('{REL}.stg_thelook__products',"
     " billing_project := 'coreychimpbot');"),
    ("bigquery_query on the same VIEW, aggregated directly, every column used",
     f"SELECT count(*) AS n, count(product_id) AS ids, any_value(typeof(cost)) AS cost_type"
     f" FROM bigquery_query('coreychimpbot',"
     f" 'SELECT product_id, cost FROM `{REL}.stg_thelook__products`',"
     " billing_project := 'coreychimpbot', use_rest_api := true);"),
    ("bigquery_query, only the SECOND of two columns used",
     f"SELECT count(*) AS n, any_value(typeof(cost)) AS cost_type FROM bigquery_query("
     f"'coreychimpbot', 'SELECT product_id, cost FROM `{REL}.stg_thelook__products`',"
     " billing_project := 'coreychimpbot', use_rest_api := true);"),
    ("bigquery_query, only the FIRST of two columns used",
     f"SELECT count(*) AS n, any_value(typeof(product_id)) AS id_type FROM bigquery_query("
     f"'coreychimpbot', 'SELECT product_id, cost FROM `{REL}.stg_thelook__products`',"
     " billing_project := 'coreychimpbot', use_rest_api := true);"),
    ("bigquery_query, no column used",
     f"SELECT count(*) AS n FROM bigquery_query("
     f"'coreychimpbot', 'SELECT product_id, cost FROM `{REL}.stg_thelook__products`',"
     " billing_project := 'coreychimpbot', use_rest_api := true);"),
    ("bigquery_query, plain projection of both columns",
     f"SELECT product_id, cost, typeof(cost) AS cost_type FROM bigquery_query("
     f"'coreychimpbot', 'SELECT product_id, cost FROM `{REL}.stg_thelook__products`',"
     " billing_project := 'coreychimpbot', use_rest_api := true) ORDER BY product_id LIMIT 2;"),
    ("bigquery_query materialised first (row_join.py's shape), then aggregated",
     f"CREATE TEMP TABLE v AS SELECT product_id, cost FROM bigquery_query("
     f"'coreychimpbot', 'SELECT product_id, cost FROM `{REL}.stg_thelook__products`',"
     " billing_project := 'coreychimpbot', use_rest_api := true);"
     " SELECT count(*) AS n, any_value(typeof(cost)) AS cost_type FROM v;"),
    ("bigquery_query aggregated through a subquery",
     f"SELECT count(*) AS n FROM (SELECT product_id, cost FROM bigquery_query("
     f"'coreychimpbot', 'SELECT product_id, cost FROM `{REL}.stg_thelook__products`',"
     " billing_project := 'coreychimpbot', use_rest_api := true));"),
    ("bigquery_scan on a TABLE",
     f"SELECT count(*) AS n, any_value(typeof(unit_cost)) AS unit_cost_type FROM"
     f" bigquery_scan('{REL}.dim_products', billing_project := 'coreychimpbot');"),
]
cli = os.environ.get("DUCKDB_BIN") or shutil.which("duckdb")
print(f"# {subprocess.run([cli, '--version'], capture_output=True, text=True).stdout.strip()}")
for label, sql in TRIES:
    out = subprocess.run([cli, "-init", "/dev/null", "-csv", ":memory:"], input=PRE + sql,
                         capture_output=True, text=True)
    text = (out.stdout + out.stderr).replace(KEY, "$BQ_KEYFILE").strip()
    frames = [ln for ln in text.splitlines() if ln.startswith("/")]
    text = "\n".join(ln for ln in text.splitlines() if ln and not ln.startswith("/")
                     and ln not in ("Success", "true"))
    if frames:
        text += f"\n({len(frames)} stack frames omitted)"
    print(f"\n## {label} (exit {out.returncode})\n{sql}\n{text}")
