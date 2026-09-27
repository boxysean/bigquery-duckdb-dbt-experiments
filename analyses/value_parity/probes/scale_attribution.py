"""Probe: is every value difference of the value-parity run explained by money_type()?

    python3 analyses/value_parity/probes/scale_attribution.py   # after a parity run with
                                                                 # --sources real; needs
                                                                 # BQ_KEYFILE

money_type() is decimal(18,2) on DuckDB and NUMERIC (scale 9) on BigQuery
(macros/polyglot/types.sql). For every column parity-report.json lists as different,
this recomputes the BigQuery checksum / null count / distinct count over
ROUND(<col>, 2) - the DuckDB scale - with exactly the harness's own canonical
rendering (scripts/parity.py Engine.canon), and compares with the DuckDB leg.

* "match at scale 2": the column differs only because BigQuery keeps more digits.
* "still differs": rounding to cents does not reconcile it - typically a value computed
  from already-rounded inputs on DuckDB (a sum of rounded cents) against a sum of
  unrounded values on BigQuery, i.e. the same scale difference propagated through
  arithmetic, or something else entirely; the line says which kind the column is.
Reads BigQuery with the harness's own maximum_bytes_billed.
"""
import importlib.util
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
spec = importlib.util.spec_from_file_location("parity", f"{REPO}/scripts/parity.py")
parity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parity)

report = json.load(open(f"{REPO}/parity-report.json"))
duck_leg = json.load(open(f"{REPO}/target/parity-duckdb-leg.json"))
bq_leg = json.load(open(f"{REPO}/target/parity-bigquery-leg.json"))
if report.get("sources") != "real":
    sys.exit("parity-report.json is not from a --sources real run")
bq = parity.BigQueryLeg(os.environ["BQ_KEYFILE"], "coreychimpbot")
relation = report["bq_relation"]

totals = {"match at scale 2": 0, "still differs": 0}
for m in report["models"]:
    cols = sorted({d["column"] for d in m.get("differences") or [] if d.get("column")})
    if not cols:
        continue
    model = m["model"]
    for c in cols:
        b_type = [x for x in bq_leg[model]["columns"] if x[0] == c][0]
        d_metrics = duck_leg[model]["metrics"]
        if b_type[1] == "decimal":
            expr = f"ROUND(`{c}`, 2)"
            kind = ("decimal",)
        else:
            # A float derived from money (e.g. a margin rate): the harness already
            # compares it at 6 decimal places; report it as is.
            expr = f"`{c}`"
            kind = ("float",)
        e = bq.engine
        text = e.canon(expr, kind)
        sql = (f"SELECT SUM({e.hex_to_int(e.md5_hex(text))}) AS s, "
               f"SUM(CASE WHEN `{c}` IS NULL THEN 1 ELSE 0 END) AS n, "
               f"COUNT(DISTINCT {text}) AS d FROM `{relation}.{model}`")
        _, rows = bq.query(sql)
        got = {k: int(v or 0) for k, v in rows[0].items()}
        want = {"s": d_metrics[f"{c}__sum"], "n": d_metrics[f"{c}__nulls"],
                "d": d_metrics[f"{c}__distinct"]}
        verdict = "match at scale 2" if got == want else "still differs"
        totals[verdict] += 1
        print(f"{model:36s} {c:26s} {b_type[2]:8s} {verdict:17s}"
              f" checksum duckdb {want['s']} bq@2 {got['s']}"
              f" | distinct duckdb {want['d']} bq@2 {got['d']}"
              f" | nulls duckdb {want['n']} bq@2 {got['n']}")
print(f"\ncolumns: {totals['match at scale 2']} match once BigQuery is rounded to"
      f" 2 decimals; {totals['still differs']} still differ")
