#!/usr/bin/env python3
"""Parity harness: prove - not assume - that both targets produce the same data.

    make parity                 # DuckDB vs BigQuery, plus the DuckDB baseline
    python3 scripts/parity.py   # same thing, directly

For every model in the project it compares, across two independently built legs:

  * row count,
  * column names,
  * column types (through a canonical cross-engine vocabulary, see TRAPS below),
  * one order-independent checksum per column,
  * a per-column null count and distinct count (they catch what a checksum can't),
  * the model's compiled SQL is the *same model* on both sides by construction.

Outputs, in the repository root:

  parity-report.md     human readable, one row per model plus a TRAPS section
  parity-report.json   the same content, machine readable

Exit status
  0  every gating comparison matched (see GATING) and the DuckDB baseline matched
  1  a real mismatch: a column name or a canonical column type differs between the
     targets, or the DuckDB-vs-DuckDB baseline does not reproduce itself
  2  the BigQuery leg could not be measured at all (no credentials), so parity is
     NOT established - the DuckDB numbers and the baseline are still printed

GATING
  Column names and canonical column types gate by default: they are the part of
  "the same data" that must hold no matter which rows the two legs read.

  Row counts and per-column checksums do *not* gate by default, because today the
  two legs deliberately read different data: the DuckDB target reads the
  deterministic local fixture, the BigQuery target reads the real
  bigquery-public-data.thelook_ecommerce. Their values cannot be equal and
  pretending otherwise would be a lie dressed up as a green run. Pass
  `--same-data` to make row counts and checksums gate as well - that is the mode
  cards 5/6 will need once a single dataset feeds both legs.

ONE DATASET ON BOTH LEGS (make value-parity; SPEC-value-parity.md)
  --sources real            dev.duckdb holds the real thelook_ecommerce rows, loaded by
                            scripts/load_duckdb_real_sources.sh (make fixtures-real). Only
                            `dbt build --target duckdb` runs - never `make duck`, whose
                            fixture reload would overwrite them. Refuses to start unless
                            the real load (not the fixture, not a raw probe) is present.
  --bq-source materialised  measure the tables and views `dbt build --target bigquery`
                            wrote to <project>.experiments_<DBT_ENV>, instead of the
                            read-only inlined compile (the default, `compiled`).
  --out-dir DIR             also write DIR/results.{md,json}, and into DIR/logs/ the raw
                            output of every build and a copy of each run_results.json.
  In these modes every model also carries dbt's per-model execution_time on both legs
  and their ratio. The defaults (fixture, compiled) print exactly what they always did.

TRAPS (each one is a decision, not a shrug)
  1. BIGNUMERIC. DuckDB DECIMAL tops out at 38 digits, so a 77-digit BIGNUMERIC
     arrives as VARCHAR and nothing can be done about the precision; the canonical
     type says `bignumeric` vs `string` and the report names it rather than hiding it.
  2. NUMERIC(38,9). Survives as a decimal on both engines. Canonical types compare
     the *kind* (decimal == numeric), never the precision, because the engines
     declare different precisions for the same value: DuckDB DECIMAL(18,2) vs
     BigQuery NUMERIC. Both raw type strings are always in the report.
  3. Floating point. Never compared as text and never with a widened tolerance:
     both sides render the value as `ROUND(x * 1000000)` micro-units, an integer,
     then hash it. One rule, identical on both engines.
  4. TIMESTAMP vs TIMESTAMPTZ. Compared as *instants*: DuckDB `epoch_us(x)`,
     BigQuery `UNIX_MICROS(x)`, i.e. microseconds since the epoch in UTC. A
     DuckDB TIMESTAMPTZ that carries a non-UTC offset and a BigQuery TIMESTAMP
     normalised to UTC agree iff they are the same instant, which is the question.
  5. Arrays and structs. Compared structurally, not textually: an array is sorted
     and joined with '|', a struct is rendered field by field through the same
     canonical rules, recursively. No union they contain is compared as raw JSON.
  6. NULLS ordering / row order. Nothing in this harness depends on row order:
     every metric is an aggregate, the checksum is a sum of per-row hashes over a
     canonicalised value, and the one place a sort is used (arrays) is a sort of
     the *values* on both engines, so the order the engine returns rows in never
     enters the comparison.
  7. NULLs themselves. A SUM over a column ignores NULL rows, so every column also
     carries an explicit null count and a distinct count; a column that is all-NULL
     on one side and missing on the other cannot slip through as "0 == 0".

The checksum is deliberately a portable construction rather than each engine's
native hash: `hash()` on DuckDB and `FARM_FINGERPRINT()` on BigQuery are different
algorithms and their results could never be compared. Instead both engines compute
`md5(<canonical text>)`, take the first 8 hex digits as an unsigned 32-bit integer
and SUM it. SUM (not XOR) so that a duplicated row changes the answer; 32 bits so
that even 2^31 rows cannot overflow a signed 64-bit sum. Every run begins by
rendering that construction over a fixture of constants on both engines and
refusing to measure anything if the two disagree (`--self-check` runs just that
step), so the portability of the digest is verified, not assumed.
"""
from __future__ import annotations

import argparse
import base64
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
DBT = REPO / ".venv" / "bin" / "dbt"
BQ_API = "https://bigquery.googleapis.com/bigquery/v2/projects/{project}/queries"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = ("https://www.googleapis.com/auth/bigquery "
         "https://www.googleapis.com/auth/cloud-platform")

HEX_DIGITS = 8          # 32 bits; 2^32 * 2^31 rows < 2^63, so a SUM cannot overflow
MAX_BYTES = int(os.environ.get("BQ_MAXIMUM_BYTES_BILLED", "1000000000"))
# Mirrors profiles.yml: schema: "experiments_{{ env_var('DBT_ENV', 'dev') }}"
SCHEMA = f"experiments_{os.environ.get('DBT_ENV', 'dev')}"


# --------------------------------------------------------------------------- io
def log(msg: str) -> None:
    print(msg, flush=True)


def dbt_env() -> dict:
    env = dict(os.environ)
    env["DBT_PROFILES_DIR"] = str(REPO)
    env.setdefault("PATH", "")
    return env


def bq_build_env(key) -> dict:
    """dbt_env() for a `dbt build --target bigquery` with a key file.

    profiles.yml defaults to `method: oauth`, which ignores `keyfile:`; with a key file
    the build must ask for the service-account method, exactly as scripts/run_bq.sh does.
    """
    env = dbt_env()
    if key:
        env.setdefault("BQ_KEYFILE", key)
        env.setdefault("BQ_AUTH_METHOD", "service-account")
    return env


def run(cmd, cwd=None, env=None, timeout=1200):
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True,
                          timeout=timeout)


# ------------------------------------------------------------------- type models
def duck_kind(type_str: str):
    """DuckDB type string -> canonical kind tuple."""
    t = type_str.strip()
    u = t.upper()
    if u.endswith("[]"):
        return ("array", duck_kind(t[:-2]))
    if u.startswith("STRUCT"):
        return ("struct", _parse_struct_body(t[len("STRUCT"):], duck_kind))
    if u.startswith("MAP") or u.startswith("LIST") or u.startswith("UNION"):
        return ("unknown", t)
    if u in ("BIGINT", "INTEGER", "INT", "SMALLINT", "TINYINT", "HUGEINT",
             "UBIGINT", "UINTEGER", "USMALLINT", "UTINYINT", "INT64"):
        return ("int",)
    if u in ("DOUBLE", "FLOAT", "REAL", "FLOAT8", "FLOAT4", "FLOAT64"):
        return ("float",)
    if u in ("BOOLEAN", "BOOL"):
        return ("bool",)
    if u == "DATE":
        return ("date",)
    if u.startswith("TIMESTAMP") or u in ("DATETIME",):
        return ("timestamp",)
    if u in ("VARCHAR", "TEXT", "STRING", "CHAR", "BPCHAR", "UUID"):
        return ("string",)
    if u.startswith("DECIMAL") or u.startswith("NUMERIC"):
        return ("decimal",)
    if u == "JSON":
        return ("json",)
    if u in ("BLOB", "BYTEA", "BYTES"):
        return ("bytes",)
    return ("unknown", t)


def _parse_struct_body(body: str, kind_of):
    """Parse `(a INTEGER, b VARCHAR)` into [(name, kind), ...]."""
    inner = body.strip()
    if inner.startswith("(") and inner.endswith(")"):
        inner = inner[1:-1]
    fields, depth, buf = [], 0, ""
    for ch in inner:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            fields.append(buf)
            buf = ""
        else:
            buf += ch
    if buf.strip():
        fields.append(buf)
    out = []
    for f in fields:
        name, _, type_str = f.strip().partition(" ")
        out.append((name.strip('"'), kind_of(type_str.strip())))
    return out


def bq_kind(field: dict):
    """BigQuery schema field -> canonical kind tuple."""
    t = (field.get("type") or "").upper()
    base = {
        "INTEGER": ("int",), "INT64": ("int",),
        "FLOAT": ("float",), "FLOAT64": ("float",),
        "BOOLEAN": ("bool",), "BOOL": ("bool",),
        "DATE": ("date",),
        "DATETIME": ("timestamp",), "TIMESTAMP": ("timestamp",),
        "STRING": ("string",),
        "NUMERIC": ("decimal",), "DECIMAL": ("decimal",),
        "BIGNUMERIC": ("bignumeric",),
        "JSON": ("json",),
        "BYTES": ("bytes",),
    }.get(t)
    if base is None:
        if t in ("RECORD", "STRUCT"):
            base = ("struct", [(f["name"], bq_kind(f)) for f in field.get("fields", [])])
        else:
            base = ("unknown", t)
    if (field.get("mode") or "NULLABLE").upper() == "REPEATED":
        return ("array", base)
    return base


def kind_label(kind) -> str:
    k = kind[0]
    if k == "array":
        return f"array<{kind_label(kind[1])}>"
    if k == "struct":
        return "struct<" + ",".join(f"{n}:{kind_label(t)}" for n, t in kind[1]) + ">"
    return {
        "int": "int64", "float": "float64", "bool": "bool", "date": "date",
        "timestamp": "timestamp", "string": "string", "decimal": "decimal",
        "bignumeric": "bignumeric", "json": "json", "bytes": "bytes",
    }.get(k, f"unknown({kind[1] if len(kind) > 1 else '?'})")


# ------------------------------------------------------- canonical SQL rendering
class Engine:
    """Per-engine SQL spellings for the canonical rendering of one value."""

    def __init__(self, name):
        self.name = name

    @property
    def text_type(self):
        return "STRING" if self.name == "bigquery" else "VARCHAR"

    def quote(self, ident):
        return f"`{ident}`" if self.name == "bigquery" else f'"{ident}"'

    def md5_hex(self, expr):
        return (f"TO_HEX(MD5({expr}))" if self.name == "bigquery"
                else f"md5({expr})")

    def hex_to_int(self, hex_expr):
        # '0x....' -> integer. Both engines parse the hex string literal.
        if self.name == "bigquery":
            return f"CAST(CONCAT('0x', SUBSTR({hex_expr}, 1, {HEX_DIGITS})) AS INT64)"
        return f"CAST(('0x' || substr({hex_expr}, 1, {HEX_DIGITS})) AS BIGINT)"

    def to_text(self, expr):
        return f"CAST({expr} AS {self.text_type})"

    def canon(self, expr, kind) -> str:
        """A text rendering of `expr` that is identical on both engines."""
        k = kind[0]
        if k == "int":
            return self.to_text(expr)
        if k == "bool":
            return self.to_text(expr)
        if k == "decimal":
            # The engines print one decimal value differently: DuckDB keeps the declared
            # scale (DECIMAL(18,2) 12.30 -> '12.30', 12 -> '12.00'), BigQuery NUMERIC
            # prints the shortest form ('12.3', '12'). Measured on 2026-09-27 (value
            # parity card): without this, equal cents hashed differently. So both sides
            # drop trailing fractional zeros (and a bare '.'); integers are untouched.
            if self.name == "bigquery":
                return (f"REGEXP_REPLACE({self.to_text(expr)}, "
                        r"r'(\.[0-9]*[1-9])0+$|\.0+$', r'\1')")
            return (f"regexp_replace({self.to_text(expr)}, "
                    r"'(\.[0-9]*[1-9])0+$|\.0+$', '\1')")
        if k == "bignumeric":
            return self.to_text(expr)
        if k == "date":
            return self.to_text(expr)
        if k == "timestamp":
            micros = (f"UNIX_MICROS({expr})" if self.name == "bigquery"
                      else f"epoch_us({expr})")
            return self.to_text(micros)
        if k == "float":
            rounded = (f"CAST(ROUND(CAST({expr} AS FLOAT64) * 1000000) AS INT64)"
                       if self.name == "bigquery"
                       else f"CAST(round(CAST({expr} AS DOUBLE) * 1000000) AS BIGINT)")
            return self.to_text(rounded)
        if k == "string" or k == "bytes":
            return (f"CAST({expr} AS STRING)" if self.name == "bigquery" else expr)
        if k == "json":
            return (f"TO_JSON_STRING({expr})" if self.name == "bigquery"
                    else f"CAST({expr} AS VARCHAR)")
        if k == "array":
            elem = kind[1]
            if self.name == "bigquery":
                rendered = self.canon("x", elem)
                return (f"ARRAY_TO_STRING(ARRAY(SELECT {rendered} AS e "
                        f"FROM UNNEST({expr}) AS x ORDER BY e), '|')")
            rendered = self.canon("x", elem)
            return (f"array_to_string(list_sort(list_transform({expr}, "
                    f"x -> {rendered})), '|')")
        if k == "struct":
            parts = [self.canon(self._field(expr, n), t) for n, t in kind[1]]
            if self.name == "bigquery":
                joined = " || '|' || ".join(
                    f"COALESCE({p}, '<null>')" for p in parts) or "''"
                return joined
            return ("concat_ws('|', " + ", ".join(f"COALESCE({p}, '<null>')" for p in parts)
                    + ")")
        return self.to_text(expr)

    def _field(self, expr, name):
        return (f"{expr}.{self.quote(name)}" if self.name == "bigquery"
                else f"{expr}.{self.quote(name)}")


# --------------------------------------------------------------- measurements
def metrics_sql(engine: Engine, source: str, columns) -> str:
    """One row: the row count plus three aggregates per column."""
    parts = ["COUNT(*) AS __rows"]
    for name, kind in columns:
        col = engine.quote(name)
        text = engine.canon(col, kind)
        safe = re.sub(r"\W", "_", name)
        parts.append(f"SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END) "
                     f"AS {engine.quote(safe + '__nulls')}")
        parts.append(f"SUM({engine.hex_to_int(engine.md5_hex(text))}) "
                     f"AS {engine.quote(safe + '__sum')}")
        parts.append(f"COUNT(DISTINCT {text}) AS {engine.quote(safe + '__distinct')}")
    return "SELECT " + ", ".join(parts) + " FROM " + source


# ------------------------------------------------------------------ DuckDB leg
def last_json(text: str):
    """The last JSON document in the DuckDB CLI's stdout, skipping any non-JSON noise.

    Not a plain json.loads(stdout): DuckDB 1.5.5 prints the lambda deprecation WARNING
    ("Deprecated lambda arrow (->) detected ...") to stdout, ANSI-coloured, before the
    JSON -- that is what broke the first array column (list_transform in Engine.canon).
    Try each '[' / '{' as a document start; the colour code shares the JSON's line."""
    dec, pos, found, last = json.JSONDecoder(), 0, False, None
    while True:
        starts = [i for i in (text.find("[", pos), text.find("{", pos)) if i >= 0]
        if not starts:
            # Nothing parsed: let json.loads raise exactly as it always has.
            return last if found else json.loads(text)
        try:
            last, pos = dec.raw_decode(text, min(starts))
            found = True
        except json.JSONDecodeError:
            pos = min(starts) + 1


class DuckLeg:
    name = "duckdb"
    engine = Engine("duckdb")

    def __init__(self, db_path: Path):
        self.db = Path(db_path)
        self.cli = (os.environ.get("DUCKDB_BIN")
                    or shutil.which("duckdb") or str(REPO / ".venv" / "bin" / "duckdb"))

    def sql(self, query: str):
        out = run([self.cli, "-json", "-init", "/dev/null", str(self.db), query])
        if out.returncode != 0:
            raise RuntimeError(out.stderr.strip() or out.stdout.strip())
        return last_json(out.stdout)

    def schema(self, model):
        rows = self.sql(
            "select column_name, data_type from information_schema.columns "
            f"where table_schema = 'main' and table_name = {model!r} "
            "order by ordinal_position")
        return [(r["column_name"], duck_kind(r["data_type"]), r["data_type"]) for r in rows]

    def measure(self, model, columns):
        source = f'main."{model}"'
        rows = self.sql(metrics_sql(self.engine, source, [(n, k) for n, k, _ in columns]))
        return _normalise(rows[0], columns)


# --------------------------------------------------------------- BigQuery leg
def access_token(key_path: str) -> str:
    with open(key_path) as fh:
        info = json.load(fh)

    def b64(data):
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    header = b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    now = int(time.time())
    claims = b64(json.dumps({
        "iss": info["client_email"], "scope": SCOPE, "aud": TOKEN_URL,
        "iat": now, "exp": now + 3600}).encode())
    signing_input = f"{header}.{claims}"
    with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as kf:
        kf.write(info["private_key"])
        pem = kf.name
    try:
        sig = subprocess.run(["openssl", "dgst", "-sha256", "-sign", pem],
                             input=signing_input.encode(), capture_output=True,
                             check=True).stdout
    finally:
        os.unlink(pem)
    body = urllib.parse.urlencode({
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
        "assertion": f"{signing_input}.{b64(sig)}"}).encode()
    with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=body),
                                timeout=60) as resp:
        return json.loads(resp.read().decode())["access_token"]


class BigQueryLeg:
    name = "bigquery"
    engine = Engine("bigquery")

    def __init__(self, key_path: str, project: str):
        self.key = key_path
        self.project = project
        self._token = None

    @property
    def token(self):
        if self._token is None:
            self._token = access_token(self.key)
        return self._token

    def query(self, sql: str, extra: dict | None = None):
        """(schema fields, rows as list-of-dict-of-text).

        jobs.query waits at most its timeoutMs (default 10 s) and then answers
        `jobComplete: false` with no rows; the job keeps running. Measured on
        2026-09-28: the uncached metrics query of int_order_items__enriched took 9.5 s,
        and one run over the limit made measure_of's rows[0] raise "list index out of
        range". So an incomplete answer is polled with getQueryResults until it is done.
        `extra` merges into the request body (tests force timeoutMs=1 with it).
        """
        body = {"query": sql, "useLegacySql": False, "maximumBytesBilled": str(MAX_BYTES)}
        body.update(extra or {})
        req = urllib.request.Request(BQ_API.format(project=self.project),
                                     data=json.dumps(body).encode())
        req.add_header("Authorization", "Bearer " + self.token)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=900) as resp:
                out = json.loads(resp.read().decode())
            deadline = time.time() + 900
            while not out.get("jobComplete", True):
                if time.time() > deadline:
                    raise RuntimeError("BigQuery job did not complete within 900 s")
                ref = out["jobReference"]
                poll = urllib.request.Request(
                    f"{BQ_API.format(project=self.project)}/{ref['jobId']}?"
                    + urllib.parse.urlencode({"location": ref.get("location", ""),
                                              "timeoutMs": 60000}))
                poll.add_header("Authorization", "Bearer " + self.token)
                with urllib.request.urlopen(poll, timeout=900) as resp:
                    out = {**json.loads(resp.read().decode()), "jobReference": ref}
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"BigQuery HTTP {e.code}: {e.read().decode()[:600]}")
        fields = out.get("schema", {}).get("fields", [])
        rows = []
        for row in out.get("rows", []):
            rows.append({f["name"]: c.get("v") for f, c in zip(fields, row.get("f", []))})
        return fields, rows

    def dataset_status(self, dataset):
        """Read-only existence check of a dataset, for the report."""
        url = (f"https://bigquery.googleapis.com/bigquery/v2/projects/"
               f"{self.project}/datasets/{dataset}")
        req = urllib.request.Request(url)
        req.add_header("Authorization", "Bearer " + self.token)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            try:
                return e.code, json.loads(body)
            except Exception:
                return e.code, {"raw": body}

    def schema(self, model, compiled):
        return self.schema_of(f"(\n{compiled}\n) AS _m")

    def measure(self, model, columns, compiled):
        return self.measure_of(f"(\n{compiled}\n) AS _m", columns)

    # `source` is anything a FROM accepts: the inlined compile above, or a
    # materialised table `project.dataset.model` (--bq-source materialised).
    def schema_of(self, source):
        fields, _ = self.query(f"SELECT * FROM {source} LIMIT 0")
        return [(f["name"], bq_kind(f), _bq_type_str(f)) for f in fields]

    def measure_of(self, source, columns):
        sql = metrics_sql(self.engine, source, [(n, k) for n, k, _ in columns])
        _, rows = self.query(sql)
        return _normalise(rows[0], columns)


def _bq_type_str(field):
    t = field["type"]
    if (field.get("mode") or "").upper() == "REPEATED":
        return f"ARRAY<{t}>"
    if t == "RECORD":
        return "STRUCT<" + ", ".join(f"{c['name']} {c['type']}"
                                     for c in field.get("fields", [])) + ">"
    return t


def _normalise(row, columns) -> dict:
    """Text-or-number metrics -> {metric: int}, with SUM(NULL) -> 0."""
    out = {"__rows": int(row["__rows"])}
    for name, _kind, _raw in columns:
        safe = re.sub(r"\W", "_", name)
        for suffix in ("nulls", "sum", "distinct"):
            v = row.get(f"{safe}__{suffix}")
            out[f"{name}__{suffix}"] = 0 if v in (None, "") else int(v)
    return out


# ------------------------------------------------------------------- reporting
def model_verdict(duck_model, bq_model, same_rows=False):
    """Compare one model on both legs; returns (verdict, list-of-differences).

    `same_rows`: both legs read the same input rows (--sources real), so a row or
    value difference is a result difference, not a data difference.
    """
    row_detail = ("same input rows, different row count" if same_rows
                  else "the two legs read different source data")
    value_detail = ("same input rows, different values" if same_rows
                    else "different source data")
    diffs = []
    d_names = [c[0] for c in duck_model["columns"]]
    b_names = [c[0] for c in bq_model["columns"]]
    if d_names != b_names:
        missing = [c for c in d_names if c not in b_names]
        extra = [c for c in b_names if c not in d_names]
        order = d_names == b_names is False and sorted(d_names) == sorted(b_names)
        diffs.append({"check": "column_names", "duckdb": d_names, "bigquery": b_names,
                      "detail": ("same set, different order" if order else
                                 f"only in duckdb: {missing}; only in bigquery: {extra}")})
    d_types = {c[0]: kind_label(c[1]) for c in duck_model["columns"]}
    b_types = {c[0]: kind_label(c[1]) for c in bq_model["columns"]}
    for name in d_names:
        if name in b_types and d_types[name] != b_types[name]:
            diffs.append({"check": "column_type", "column": name,
                          "duckdb": d_types[name], "bigquery": b_types[name],
                          "detail": (f'raw types: duckdb '
                                     f'{[c[2] for c in duck_model["columns"] if c[0] == name][0]}'
                                     f' vs bigquery '
                                     f'{[c[2] for c in bq_model["columns"] if c[0] == name][0]}')})
    if duck_model["metrics"]["__rows"] != bq_model["metrics"]["__rows"]:
        diffs.append({"check": "row_count",
                      "duckdb": duck_model["metrics"]["__rows"],
                      "bigquery": bq_model["metrics"]["__rows"],
                      "detail": row_detail})
    for name in d_names:
        if name not in b_types:
            continue
        for suffix, label in (("sum", "checksum"), ("nulls", "null_count"),
                              ("distinct", "distinct_count")):
            dv = duck_model["metrics"].get(f"{name}__{suffix}")
            bv = bq_model["metrics"].get(f"{name}__{suffix}")
            if dv != bv:
                diffs.append({"check": f"column_{label}", "column": name,
                              "duckdb": dv, "bigquery": bv,
                              "detail": value_detail})
    gating = [d for d in diffs if d["check"] in ("column_names", "column_type")]
    return ("match" if not diffs else "differs"), diffs, bool(gating)


# ------------------------------------------------------------------- the driver
def discover_models():
    out = run([str(DBT), "ls", "--quiet", "--target", "duckdb",
               "--resource-type", "model", "--output", "json",
               "--output-keys", "name"], cwd=str(REPO), env=dbt_env())
    names = re.findall(r'"name"\s*:\s*"([^"]+)"', out.stdout)
    seen, ordered = set(), []
    for n in names:
        if n not in seen:
            seen.add(n)
            ordered.append(n)
    return ordered


def compile_ephemeral_bigquery(tmp: Path):
    """Compile every model into one self-contained BigQuery query.

    All layers are ephemeral, so `dbt compile` emits the whole DAG inlined as
    `__dbt__cte__…` CTEs and each model becomes a plain SELECT. That can be run as
    a query, which needs no dataset-write permission.
    """
    (tmp / "dbt_project.yml").write_text(
        "name: bq_duckdb_experiments\n"
        "profile: bq_duckdb_experiments\n"
        'model-paths: ["models"]\n'
        'macro-paths: ["macros"]\n'
        'test-paths: ["tests"]\n'
        "models:\n"
        "  bq_duckdb_experiments:\n"
        "    staging:\n      +materialized: ephemeral\n"
        "    intermediate:\n      +materialized: ephemeral\n"
        "    marts:\n      +materialized: ephemeral\n")
    for d in ("models", "macros", "tests"):
        os.symlink(REPO / d, tmp / d)
    out = run([str(DBT), "compile", "--target", "bigquery", "--project-dir", str(tmp)],
              cwd=str(REPO), env=dbt_env())
    if out.returncode != 0:
        raise RuntimeError(out.stdout[-2000:] + out.stderr[-2000:])
    compiled = {}
    for path in (tmp / "target" / "compiled").rglob("models/**/*.sql"):
        compiled[path.stem] = path.read_text()
    return compiled


def digest_selfcheck(duck: DuckLeg, bq: BigQueryLeg):
    """Both engines must agree on the digest construction for constant inputs."""
    # Written out longhand so the two spellings are visible side by side. Rows 3-4
    # carry decimals with trailing zeros (12.30, 12.00): DuckDB prints them at the
    # declared scale and BigQuery in the shortest form, which the first two rows
    # could never show (see Engine.canon, kind "decimal").
    duck_sql = r"""
select
  sum(cast(('0x'||substr(md5(cast(i as varchar)),1,8)) as bigint)) as int_sum,
  sum(cast(('0x'||substr(md5(cast(cast(round(f*1000000) as bigint) as varchar)),1,8)) as bigint)) as float_sum,
  sum(cast(('0x'||substr(md5(cast(b as varchar)),1,8)) as bigint)) as bool_sum,
  sum(cast(('0x'||substr(md5(cast(d as varchar)),1,8)) as bigint)) as date_sum,
  sum(cast(('0x'||substr(md5(cast(epoch_us(ts) as varchar)),1,8)) as bigint)) as ts_sum,
  sum(cast(('0x'||substr(md5(s),1,8)) as bigint)) as str_sum,
  sum(cast(('0x'||substr(md5(regexp_replace(cast(dec as varchar), '(\.[0-9]*[1-9])0+$|\.0+$', '\1')),1,8)) as bigint)) as dec_sum,
  count(distinct cast(f as varchar)) as f_distinct
from (values
  (1, 1.5, true,  date '2024-03-15', timestamp '2024-03-15 13:45:12', 'abc', 12.34::decimal(18,2)),
  (2, -2.25, false, date '2023-01-01', timestamp '2023-01-01 00:00:00', 'ABC', -0.05::decimal(18,2)),
  (3, 0.5, true,  date '2024-02-29', timestamp '2024-02-29 23:59:59', 'x', 12.30::decimal(18,2)),
  (4, 100.0, false, date '1999-12-31', timestamp '1999-12-31 12:00:00', '', 12.00::decimal(18,2))
) t(i,f,b,d,ts,s,dec)
"""
    bq_sql = r"""
select
  sum(cast(concat('0x', substr(to_hex(md5(cast(i as string))),1,8)) as int64)) as int_sum,
  sum(cast(concat('0x', substr(to_hex(md5(cast(cast(round(f*1000000) as int64) as string))),1,8)) as int64)) as float_sum,
  sum(cast(concat('0x', substr(to_hex(md5(cast(b as string))),1,8)) as int64)) as bool_sum,
  sum(cast(concat('0x', substr(to_hex(md5(cast(d as string))),1,8)) as int64)) as date_sum,
  sum(cast(concat('0x', substr(to_hex(md5(cast(unix_micros(ts) as string))),1,8)) as int64)) as ts_sum,
  sum(cast(concat('0x', substr(to_hex(md5(s)),1,8)) as int64)) as str_sum,
  sum(cast(concat('0x', substr(to_hex(md5(regexp_replace(cast(dec as string), r'(\.[0-9]*[1-9])0+$|\.0+$', r'\1'))),1,8)) as int64)) as dec_sum,
  count(distinct cast(f as string)) as f_distinct
from unnest([
  struct(1 as i, 1.5 as f, true as b, date '2024-03-15' as d, timestamp '2024-03-15 13:45:12' as ts, 'abc' as s, numeric '12.34' as dec),
  struct(2 as i, -2.25 as f, false as b, date '2023-01-01' as d, timestamp '2023-01-01 00:00:00' as ts, 'ABC' as s, numeric '-0.05' as dec),
  struct(3 as i, 0.5 as f, true as b, date '2024-02-29' as d, timestamp '2024-02-29 23:59:59' as ts, 'x' as s, numeric '12.30' as dec),
  struct(4 as i, 100.0 as f, false as b, date '1999-12-31' as d, timestamp '1999-12-31 12:00:00' as ts, '' as s, numeric '12.00' as dec)
])
"""
    d = duck.sql(duck_sql)[0]
    _, brows = bq.query(bq_sql)
    b = {k: int(v) for k, v in brows[0].items()}
    d = {k: int(v) for k, v in d.items()}
    return d, b, d == b


def real_sources_problem(duck: DuckLeg):
    """None when dev.duckdb holds the real load of scripts/load_duckdb_real_sources.sh.

    The real tables have a `users.user_geom` column the fixture lacks, and the loader
    delivers timestamps as TIMESTAMPTZ (D2) where the extension alone gives TIMESTAMP;
    together they tell the real load apart from the fixture and from a raw probe load.
    """
    try:
        rows = duck.sql(
            "select table_name, column_name, data_type from information_schema.columns "
            "where table_schema = 'thelook_ecommerce' and ("
            "(table_name = 'users' and column_name = 'user_geom') or "
            "(table_name = 'orders' and column_name = 'created_at'))")
    except Exception as e:  # noqa: BLE001
        return f"cannot read {duck.db}: {e}"
    found = {(r["table_name"], r["column_name"]): r["data_type"] for r in rows}
    if ("users", "user_geom") not in found:
        return ("thelook_ecommerce.users has no user_geom column: dev.duckdb holds the"
                " fixture, not the real dataset")
    if found.get(("orders", "created_at")) != "TIMESTAMP WITH TIME ZONE":
        return (f"thelook_ecommerce.orders.created_at is"
                f" {found.get(('orders', 'created_at'))}, not TIMESTAMP WITH TIME ZONE:"
                " a raw-timestamp load breaks the source contract (D2)")
    return None


def layer_of(model: str) -> str:
    for layer in ("staging", "intermediate", "marts"):
        if any((REPO / "models" / layer).rglob(f"{model}.sql")):
            return layer
    return "?"


def keep_run_results(leg: str, out_dir):
    """Copy target/run_results.json aside before the next build overwrites it."""
    src = REPO / "target" / "run_results.json"
    if not src.exists():
        return None
    dst = REPO / "target" / f"parity-run_results-{leg}.json"
    shutil.copyfile(src, dst)
    if out_dir:
        shutil.copyfile(src, out_dir / "logs" / f"run_results_{leg}.json")
    return dst


def model_durations(path) -> dict:
    """{model name: execution_time seconds} from a run_results.json copy."""
    if not path or not Path(path).exists():
        return {}
    data = json.loads(Path(path).read_text())
    out = {}
    for r in data.get("results", []):
        uid = r.get("unique_id", "")
        if uid.startswith("model.") and r.get("execution_time") is not None:
            out[uid.split(".")[-1]] = float(r["execution_time"])
    return out


def write_build_log(out_dir, name, cmd, out, wall):
    """The raw bytes a build printed, for analyses/<dir>/logs/."""
    if not out_dir:
        return
    text = (f"$ {' '.join(cmd)}\n# exit {out.returncode}, wall {wall:.2f} s\n"
            + out.stdout + ("\n# --- stderr ---\n" + out.stderr if out.stderr else ""))
    # The logs are committed; the key path stays out of them.
    for var in ("BQ_KEYFILE", "GOOGLE_APPLICATION_CREDENTIALS"):
        if os.environ.get(var):
            text = text.replace(os.environ[var], f"${var}")
    (out_dir / "logs" / name).write_text(text)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--baseline", action="store_true", default=True,
                    help="also rebuild DuckDB and prove it reproduces (default: on)")
    ap.add_argument("--no-baseline", dest="baseline", action="store_false")
    ap.add_argument("--same-data", action="store_true",
                    help="gate on row counts and checksums too (both legs read one dataset)")
    ap.add_argument("--skip-build", action="store_true",
                    help="measure what is already built instead of building")
    ap.add_argument("--self-check", dest="self_check", action="store_true",
                    help="run only the digest self-check (both engines, constant inputs)"
                         " and exit; no build, no models")
    ap.add_argument("--project", default="coreychimpbot")
    ap.add_argument("--sources", choices=("fixture", "real"), default="fixture",
                    help="what dev.duckdb reads: `fixture` (default; `make duck` reloads it)"
                         " or `real` (the tables scripts/load_duckdb_real_sources.sh"
                         " loaded; only `dbt build --target duckdb` runs, never the"
                         " fixture loader, which would overwrite them)")
    ap.add_argument("--bq-source", dest="bq_source", choices=("compiled", "materialised"),
                    default="compiled",
                    help="what is measured on BigQuery: `compiled` (default; the DAG"
                         " inlined into one read-only query per model) or `materialised`"
                         " (the tables `dbt build --target bigquery` wrote to"
                         " <project>.<schema>)")
    ap.add_argument("--out-dir", dest="out_dir", type=Path,
                    help="also write results.md/.json there and the raw build logs and"
                         " run_results copies into <out-dir>/logs/"
                         " (e.g. analyses/value_parity)")
    args = ap.parse_args()
    # The fixture + compiled defaults are the path every other card and the pre-PR gate
    # use; their output stays exactly as it was. Durations and the value-parity wording
    # are only added once one of the new modes is asked for.
    extended = (args.sources == "real" or args.bq_source == "materialised"
                or args.out_dir is not None)
    out_dir = None
    if args.out_dir is not None:
        out_dir = (args.out_dir if args.out_dir.is_absolute() else REPO / args.out_dir)
        (out_dir / "logs").mkdir(parents=True, exist_ok=True)

    key = (os.environ.get("BQ_KEYFILE")
           or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))
    if key and not Path(key).exists():
        log(f"WARNING: the key file {key} does not exist; treating the BigQuery leg"
            " as unavailable.")
        key = None

    if args.self_check:
        duck = DuckLeg(REPO / "dev.duckdb" if (REPO / "dev.duckdb").exists()
                       else Path(":memory:"))
        if not key or not shutil.which("openssl"):
            log("self-check needs the BigQuery leg (BQ_KEYFILE + openssl);"
                " cannot run.")
            return 2
        d, b, ok = digest_selfcheck(duck, BigQueryLeg(key, args.project))
        for k in sorted(d):
            log(f"  {k:12s} duckdb {d[k]:>14d}   bigquery {b.get(k):>14d}"
                f"   {'ok' if d[k] == b.get(k) else 'MISMATCH'}")
        log(f"digest self-check: {'PASS' if ok else 'FAIL'}")
        return 0 if ok else 1

    started = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    report = {"generated_at": started, "same_data": args.same_data,
              "models": [], "baseline": {}, "self_check": {}, "legs": {}}
    if extended:
        report.update({"sources": args.sources, "bq_source": args.bq_source,
                       "bq_relation": f"{args.project}.{SCHEMA}"})
    if args.same_data and args.sources == "fixture":
        log("WARNING: --same-data with --sources fixture: the DuckDB leg reads the"
            " fixture and BigQuery the real dataset, so rows and checksums will differ"
            " and gate. Load the real rows (make fixtures-real) and pass --sources real.")
    run_results = {"duckdb": REPO / "target" / "parity-run_results-duckdb.json",
                   "bigquery": REPO / "target" / "parity-run_results-bigquery.json"}
    duck_build_failed = False

    # ---------------------------------------------------------------- DuckDB leg
    duck = DuckLeg(REPO / "dev.duckdb")
    if args.sources == "real":
        problem = (real_sources_problem(duck) if duck.db.exists()
                   else f"{duck.db} does not exist")
        if problem:
            log(f"FATAL: --sources real, but {problem}. Run `make fixtures-real`"
                " (scripts/load_duckdb_real_sources.sh) first.")
            return 1
        log("      dev.duckdb holds the real thelook_ecommerce rows"
            " (users.user_geom present, timestamps TIMESTAMPTZ)")
    if not args.skip_build and args.sources == "real":
        cmd = [str(DBT), "build", "--target", "duckdb"]
        log("[1/5] dbt build --target duckdb  (real sources; the fixture is NOT reloaded)")
        t0 = time.time()
        out = run(cmd, cwd=str(REPO), env=dbt_env())
        wall = time.time() - t0
        write_build_log(out_dir, "dbt_build_duckdb.log", cmd, out, wall)
        keep_run_results("duckdb", out_dir)
        report["legs"]["duckdb_build"] = {"exit": out.returncode, "wall_s": round(wall, 2),
                                          "tail": out.stdout[-400:]}
        log(f"      exit {out.returncode}, wall {wall:.1f} s")
        if out.returncode != 0:
            # On real rows a failing test is itself a finding; the models that were
            # built are still measured, and the run cannot exit 0.
            duck_build_failed = True
            log(out.stdout[-3000:])
            log("      the DuckDB build did not pass; measuring the models that exist.")
    elif not args.skip_build:
        log("[1/5] make duck  (fixtures + dbt build --target duckdb)")
        t0 = time.time()
        out = run(["make", "duck"], cwd=str(REPO), env=dbt_env())
        wall = time.time() - t0
        if extended:
            write_build_log(out_dir, "dbt_build_duckdb.log", ["make", "duck"], out, wall)
            keep_run_results("duckdb", out_dir)
        report["legs"]["duckdb_build"] = {"exit": out.returncode,
                                          "tail": out.stdout[-400:]}
        if out.returncode != 0:
            log(out.stdout[-3000:])
            log(out.stderr[-3000:])
            log("FATAL: the DuckDB leg did not build; nothing can be compared.")
            return 1
    if not duck.db.exists():
        log(f"FATAL: {duck.db} does not exist. Run `make duck` first.")
        return 1

    models = discover_models()
    log(f"      {len(models)} models discovered")
    if not models:
        log("VACUOUS parity run: no models, so nothing was compared. Not evidence.")
        return 0

    # ---------------------------------------------------------------- self-check
    bq = None
    if key and shutil.which("openssl"):
        try:
            bq = BigQueryLeg(key, args.project)
            bq.token  # fail fast on bad credentials
            d, b, ok = digest_selfcheck(duck, bq)
            report["self_check"] = {"duckdb": d, "bigquery": b, "match": ok}
            log(f"[2/5] digest self-check: {'PASS' if ok else 'FAIL'}")
            if not ok:
                log(json.dumps(report["self_check"], indent=2))
                log("FATAL: the two engines do not agree on the digest construction;"
                    " any comparison built on it would be meaningless.")
                return 1
        except Exception as e:  # noqa: BLE001
            log(f"[2/5] BigQuery leg unavailable: {e}")
            report["legs"]["bigquery_error"] = str(e)
            bq = None
    else:
        log("[2/5] BigQuery leg unavailable: no service-account key "
            "(set BQ_KEYFILE) or no openssl")
        report["legs"]["bigquery_error"] = "no key file or openssl"

    # ------------------------------------------------------------ BigQuery build
    compiled = {}
    if bq is not None:
        if not args.skip_build:
            log("[3/5] dbt build --target bigquery (attempt)")
            cmd = [str(DBT), "build", "--target", "bigquery"]
            t0 = time.time()
            out = run(cmd, cwd=str(REPO), env=bq_build_env(key))
            wall = time.time() - t0
            if extended:
                write_build_log(out_dir, "dbt_build_bigquery.log", cmd, out, wall)
                keep_run_results("bigquery", out_dir)
            first_err = ""
            if out.returncode != 0:
                blob = out.stdout + "\n" + out.stderr
                lines = blob.splitlines()
                start = next((i for i, ln in enumerate(lines) if "[error]" in ln), None)
                if start is not None:
                    block = [lines[start]]
                    for ln in lines[start + 1:start + 4]:
                        if ln.startswith(("  ", "\t")) and ln.strip():
                            block.append(ln.strip())
                        else:
                            break
                    first_err = "\n".join(block)
                else:
                    m = re.search(r"^\s*(?:Error|ERROR)\b.*$", blob, re.M)
                    first_err = m.group(0) if m else blob.strip()[-500:]
                report["legs"]["bigquery_build_tail"] = blob[-2000:]
                try:
                    code, body = bq.dataset_status(SCHEMA)
                    message = (body.get("error", {}).get("message", "")
                               if isinstance(body, dict) else str(body))
                    report["legs"]["bigquery_dataset"] = {"code": code,
                                                          "message": message}
                    log(f"      dataset {args.project}.{SCHEMA}: HTTP {code}"
                        f" {message[:80]}")
                except Exception as e:  # noqa: BLE001
                    report["legs"]["bigquery_dataset"] = {"error": str(e)}
            report["legs"]["bigquery_build"] = {"exit": out.returncode,
                                                "first_error": first_err}
            if extended:
                report["legs"]["bigquery_build"]["wall_s"] = round(wall, 2)
            log(f"      exit {out.returncode}"
                + (f" - {first_err[:160]}" if first_err else ""))
        if args.bq_source == "compiled":
            log("[3/5] compiling the DAG read-only for BigQuery (all layers ephemeral)")
            tmp = Path(tempfile.mkdtemp(prefix="parity-eph-"))
            try:
                compiled = compile_ephemeral_bigquery(tmp)
            except Exception as e:  # noqa: BLE001
                log(f"      compile failed: {e}")
                report["legs"]["bigquery_compile_error"] = str(e)
                compiled = {}
        else:
            log(f"[3/5] measuring the materialised relations in"
                f" {args.project}.{SCHEMA} (what dbt build --target bigquery wrote)")

    # ------------------------------------------------------------------- measure
    log("[4/5] measuring every model on both legs")
    (REPO / "target").mkdir(exist_ok=True)
    duck_models, duck_missing = {}, {}
    for m in models:
        cols = duck.schema(m)
        if not cols and args.sources == "real":
            # A model the (failed) real-data build never materialised.
            duck_missing[m] = f"main.{m} does not exist in dev.duckdb"
            continue
        duck_models[m] = {"columns": cols, "metrics": duck.measure(m, cols)}
    json.dump({m: {"columns": [[c[0], kind_label(c[1]), c[2]] for c in v["columns"]],
                   "metrics": v["metrics"]} for m, v in duck_models.items()},
              open(REPO / "target" / "parity-duckdb-leg.json", "w"), indent=2)

    bq_models = {}
    if compiled:
        for m in models:
            sql = compiled.get(m)
            if sql is None:
                continue
            try:
                cols = bq.schema(m, sql)
                bq_models[m] = {"columns": cols, "metrics": bq.measure(m, cols, sql)}
            except Exception as e:  # noqa: BLE001
                bq_models[m] = {"error": str(e)}
    elif bq is not None and args.bq_source == "materialised":
        for m in models:
            source = f"`{args.project}.{SCHEMA}.{m}`"
            try:
                cols = bq.schema_of(source)
                bq_models[m] = {"columns": cols, "metrics": bq.measure_of(source, cols)}
            except Exception as e:  # noqa: BLE001
                bq_models[m] = {"error": str(e)}
    json.dump({m: ({"error": v["error"]} if "error" in v else
                   {"columns": [[c[0], kind_label(c[1]), c[2]] for c in v["columns"]],
                    "metrics": v["metrics"]})
               for m, v in bq_models.items()},
              open(REPO / "target" / "parity-bigquery-leg.json", "w"), indent=2)

    # ------------------------------------------------------------------ baseline
    baseline = {"ran": False}
    if args.baseline and not args.skip_build:
        log("[5/5] DuckDB baseline: rebuild and prove the measurements reproduce")
        before = {m: dict(v["metrics"], __cols=[c[0] for c in v["columns"]])
                  for m, v in duck_models.items()}
        # `make duck` would reload the fixture over the real rows; on real sources the
        # baseline is the build alone, reading the same loaded tables.
        cmd = (["make", "duck"] if args.sources == "fixture"
               else [str(DBT), "build", "--target", "duckdb"])
        t0 = time.time()
        out = run(cmd, cwd=str(REPO), env=dbt_env())
        if extended:
            write_build_log(out_dir, "dbt_build_duckdb_baseline.log", cmd, out,
                            time.time() - t0)
        baseline["ran"] = True
        baseline["rebuild_exit"] = out.returncode
        if out.returncode != 0:
            baseline["match"] = False
            baseline["error"] = "the second build failed"
        else:
            mismatches = {}
            for m in duck_models:
                cols = duck.schema(m)
                now = dict(duck.measure(m, cols),
                           __cols=[c[0] for c in cols])
                if now != before[m]:
                    mismatches[m] = {"before": before[m], "after": now}
            baseline["match"] = not mismatches
            baseline["mismatches"] = mismatches
        log(f"      baseline: {'MATCH' if baseline.get('match') else 'MISMATCH'}")
    report["baseline"] = baseline

    # ------------------------------------------------------------------ verdicts
    gating_failed, value_failed, unmeasured = [], [], []
    dur = {}
    if extended:
        dur = {leg: model_durations(path) for leg, path in run_results.items()}
        report["durations_source"] = {leg: (str(p.relative_to(REPO)) if p.exists() else None)
                                      for leg, p in run_results.items()}
    for m in models:
        if m in duck_missing:
            unmeasured.append(m)
            report["models"].append({"model": m, "verdict": "not_measured",
                                     "error": duck_missing[m], "runs": []})
            continue
        if m not in bq_models:
            unmeasured.append(m)
            report["models"].append({"model": m, "verdict": "not_measured",
                                     "row_count": duck_models[m]["metrics"]["__rows"],
                                     "columns": len(duck_models[m]["columns"]),
                                     "runs": ["duckdb"]})
            continue
        if "error" in bq_models[m]:
            unmeasured.append(m)
            report["models"].append({"model": m, "verdict": "not_measured",
                                     "error": bq_models[m]["error"],
                                     "row_count": duck_models[m]["metrics"]["__rows"],
                                     "columns": len(duck_models[m]["columns"]),
                                     "runs": ["duckdb"]})
            continue
        verdict, diffs, gated = model_verdict(duck_models[m], bq_models[m],
                                              same_rows=args.sources == "real")
        entry = {"model": m, "verdict": verdict,
                 "row_count": {"duckdb": duck_models[m]["metrics"]["__rows"],
                               "bigquery": bq_models[m]["metrics"]["__rows"]},
                 "columns": len(duck_models[m]["columns"]),
                 "runs": ["duckdb", "bigquery"],
                 "differences": diffs}
        report["models"].append(entry)
        if gated:
            gating_failed.append(m)
        elif diffs:
            value_failed.append(m)

    if extended:
        for entry in report["models"]:
            m = entry["model"]
            d, b = dur.get("duckdb", {}).get(m), dur.get("bigquery", {}).get(m)
            entry["layer"] = layer_of(m)
            entry["duration_s"] = {"duckdb": d, "bigquery": b,
                                   "ratio": (round(b / d, 2) if d and b else None)}

    # --------------------------------------------------------------------- write
    with open(REPO / "parity-report.json", "w") as fh:
        json.dump(report, fh, indent=2)
    write_markdown(report, args, key)

    if extended:
        print_summary(report)
    if out_dir:
        write_results(report, args, out_dir, duck, duck_build_failed)

    if bq is None or not bq_models or len(unmeasured) == len(models):
        log(f"\nparity: BigQuery leg could not be measured. Parity is NOT established.")
        log("See parity-report.md for the exact reason. DuckDB numbers above are"
            " reported for information only.")
        return 2

    gated_rows = args.same_data
    if gating_failed or (gated_rows and (value_failed or unmeasured)):
        log(f"\nparity: MISMATCH. gating: {gating_failed or 'none'};"
            f" value/row: {value_failed or 'none'}; not measured: {unmeasured or 'none'}")
        log("See parity-report.md.")
        return 1
    if baseline.get("ran") and not baseline.get("match"):
        log("\nparity: the DuckDB baseline did not reproduce; the harness itself"
            " is not trustworthy. See parity-report.md.")
        return 1
    build_failed = duck_build_failed or (
        args.bq_source == "materialised"
        and report["legs"].get("bigquery_build", {}).get("exit", 0) != 0)
    if args.sources == "real":
        equal = len(models) - len(value_failed)
        log(f"\nparity: schema parity holds on all {len(models)} models. On the same"
            f" input rows, {equal} of {len(models)} match on every check"
            + (f"; {len(value_failed)} differ on rows and/or values:"
               f" {', '.join(value_failed)}" if value_failed else "")
            + ". See parity-report.md.")
        if build_failed:
            log("parity: a build did not pass (see the build logs); not a clean run.")
        return 1 if (build_failed or (value_failed and gated_rows)) else 0
    if build_failed:
        log("\nparity: the BigQuery build did not pass; the materialised relations may be"
            " stale. See parity-report.md.")
        return 1
    if value_failed:
        log(f"\nparity: schema parity holds on all {len(models)} models. Row counts and"
            f" checksums differ on {len(value_failed)} of them, as expected: the two legs"
            " read different source data (fixture vs the real dataset). That is cards"
            " 5/6's job; run with --same-data once both legs read one dataset.")
        if gated_rows:
            return 1
    else:
        log(f"\nparity: all {len(models)} models match on both legs.")
    return 0


def _secs(v):
    return "n/a" if v is None else f"{v:.2f}"


def _rows_pair(m):
    rc = m.get("row_count")
    if isinstance(rc, dict):
        return rc["duckdb"], rc["bigquery"]
    return (rc if rc is not None else "n/a"), "n/a"


def _ratio(m):
    r = (m.get("duration_s") or {}).get("ratio")
    return "n/a" if r is None else f"{r:.1f}x"


def print_summary(report):
    """Per model, the equality result next to both build durations (D5)."""
    log("\n      model                                       layer         verdict     "
        " rows duckdb  rows bq  duckdb s    bq s  bq/duck")
    for m in report["models"]:
        rd, rb = _rows_pair(m)
        d = m.get("duration_s") or {}
        log(f"      {m['model']:43s} {m.get('layer', ''):13s} {m['verdict']:12s}"
            f" {rd!s:>11} {rb!s:>8} {_secs(d.get('duckdb')):>9}"
            f" {_secs(d.get('bigquery')):>7} {_ratio(m):>8}")


def write_results(report, args, out_dir, duck, duck_build_failed):
    """<out-dir>/results.{md,json}: generated by the run, never hand-edited."""
    with open(out_dir / "results.json", "w") as fh:
        json.dump(report, fh, indent=2)
    try:
        version = duck.sql("select version() as v")[0]["v"]
    except Exception:  # noqa: BLE001
        version = "unknown"
    models = report["models"]
    marts = [m for m in models if m.get("layer") == "marts"]
    match = [m for m in models if m["verdict"] == "match"]
    marts_match = [m for m in marts if m["verdict"] == "match"]
    real = args.sources == "real"
    flags = (f"--sources {args.sources} --bq-source {args.bq_source}"
             + (" --same-data" if args.same_data else "")
             + (" --skip-build" if args.skip_build else ""))
    lines = []
    A = lines.append
    A("# Value parity: results (generated)")
    A("")
    A(f"Generated by `scripts/parity.py {flags}` at {report['generated_at']}."
      f" DuckDB `{version}`; BigQuery relations in `{report.get('bq_relation', '')}`"
      + (" as materialised by `dbt build --target bigquery`."
         if args.bq_source == "materialised" else " (inlined compile, read-only)."))
    A("")
    if real:
        A("DuckDB leg: `dev.duckdb` built by `dbt build --target duckdb` over the real"
          " `thelook_ecommerce` rows that `scripts/load_duckdb_real_sources.sh` copied"
          " from BigQuery (timestamps delivered as TIMESTAMPTZ, D2).")
    else:
        A("DuckDB leg: `dev.duckdb` built by `make duck` over the fixture.")
    A("")
    A("Method: per model, on the relation each leg delivered: row count, column names,"
      " canonical column types, and per column an order-independent checksum (SUM of the"
      " first 32 bits of `md5(<canonical text>)`), a null count and a distinct count."
      " The digest is checked on constants on both engines before any model is"
      " measured. Durations are dbt's per-model `execution_time` from each leg's"
      " `run_results.json` (copies in `logs/`).")
    A("")
    A("## Verdict")
    A("")
    A(f"* all models: **{len(match)} of {len(models)}** match on every check.")
    A(f"* marts: **{len(marts_match)} of {len(marts)}** match on every check.")
    sc = report.get("self_check") or {}
    A("* digest self-check: "
      + ("PASS." if sc.get("match") else ("FAIL." if sc else "not run.")))
    base = report.get("baseline") or {}
    if not base.get("ran"):
        A("* DuckDB-vs-DuckDB baseline: not run (`--skip-build` or `--no-baseline`).")
    else:
        A("* DuckDB-vs-DuckDB baseline: "
          + ("MATCH." if base.get("match") else "**MISMATCH**."))
    for leg in ("duckdb_build", "bigquery_build"):
        b = report["legs"].get(leg)
        if b:
            A(f"* `{leg}`: exit {b.get('exit')}"
              + (f", wall {b['wall_s']} s" if b.get("wall_s") is not None else "") + ".")
    if duck_build_failed:
        A("* the DuckDB build did **not** pass; see `logs/dbt_build_duckdb.log`.")
    A("")
    A("## Per model")
    A("")
    A("| layer | model | rows duckdb | rows bigquery | cols | verdict | differences"
      " | duckdb s | bigquery s | bigquery/duckdb |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    order = {"marts": 0, "intermediate": 1, "staging": 2}
    for m in sorted(models, key=lambda m: (order.get(m.get("layer"), 3), m["model"])):
        rd, rb = _rows_pair(m)
        d = m.get("duration_s") or {}
        A(f"| {m.get('layer', '')} | `{m['model']}` | {rd} | {rb} | {m.get('columns', '')}"
          f" | {m['verdict']} | {len(m.get('differences') or [])}"
          f" | {_secs(d.get('duckdb'))} | {_secs(d.get('bigquery'))} | {_ratio(m)} |")
    tot_d = sum((m.get("duration_s") or {}).get("duckdb") or 0 for m in models)
    tot_b = sum((m.get("duration_s") or {}).get("bigquery") or 0 for m in models)
    A("")
    A(f"Sum of per-model execution time: DuckDB {tot_d:.2f} s, BigQuery {tot_b:.2f} s.")
    A("")
    A("## Differences, in full")
    A("")
    any_diff = False
    for m in models:
        diffs = m.get("differences") or []
        if not diffs and not m.get("error"):
            continue
        any_diff = True
        A(f"### `{m['model']}` ({m.get('layer', '')}) - {m['verdict']}")
        A("")
        if m.get("error"):
            A("```")
            A(m["error"])
            A("```")
            A("")
            continue
        A("| check | column | duckdb | bigquery | detail |")
        A("|---|---|---|---|---|")
        for d in diffs:
            A(f"| {d['check']} | {d.get('column', '')} | `{d['duckdb']}`"
              f" | `{d['bigquery']}` | {d.get('detail', '')} |")
        A("")
    if not any_diff:
        A("None: every model matched on every check.")
        A("")
    (out_dir / "results.md").write_text("\n".join(lines))


def write_markdown(report, args, key):
    bq = report["legs"].get("bigquery_build", {})
    real = report.get("sources") == "real"
    lines = []
    A = lines.append
    A("# Parity report - DuckDB vs BigQuery")
    A("")
    A(f"Generated {report['generated_at']} by `make parity` "
      "(`scripts/parity.py`).")
    A("")
    models = report["models"]
    n_all = len(models)
    gating = [m for m in models
              if any(d["check"] in ("column_names", "column_type")
                     for d in (m.get("differences") or []))]
    full = [m["model"] for m in models if m["verdict"] == "match"]
    notme = [m["model"] for m in models if m["verdict"] == "not_measured"]
    valonly = [m["model"] for m in models if m["verdict"] == "differs"
               and m["model"] not in [g["model"] for g in gating]]
    A("## Verdict")
    A("")
    if gating:
        A(f"**MISMATCH on {len(gating)} of {n_all} models** - a column name or a")
        A("canonical column type differs between the targets. That is a real defect in")
        A("the project, not a difference in source data, and it is what makes the run")
        A("exit non-zero:")
    else:
        A(f"**No column-name or column-type mismatch on any of the {n_all} models.**")
    for m in gating:
        for d in m.get("differences") or []:
            if d["check"] in ("column_names", "column_type"):
                A(f"* `{m['model']}`"
                  + (f".`{d['column']}`" if d.get("column") else "")
                  + f": duckdb `{d['duckdb']}` vs bigquery `{d['bigquery']}`"
                  + (f" ({d['detail']})" if d.get("detail") else ""))
    if gating:
        A("")
    if full:
        A(f"{len(full)} model(s) match on **every** check, values included: "
          + ", ".join(f"`{f}`" for f in full) + ".")
        A("")
    if valonly and real:
        A(f"{len(valonly)} model(s) match on names and types but differ on rows and/or")
        A("values **although both legs read the same input rows** (the real dataset,")
        A("loaded into DuckDB by `scripts/load_duckdb_real_sources.sh`). Each one is a")
        A("result difference between the targets, listed under Differences.")
        A("")
    elif valonly:
        A(f"{len(valonly)} model(s) match on names and types but differ on rows and/or")
        A("values, because the two legs read different source data (the DuckDB fixture")
        A("vs the real dataset). Expected today; cards 5/6 remove the cause.")
        A("")
    if notme:
        A(f"{len(notme)} model(s) could not be measured on the BigQuery leg: "
          + ", ".join(f"`{f}`" for f in notme) + ".")
        A("")
    if not real:
        A("A model that matches values **as well as** schema is the strongest signal in")
        A("this report: it means the fixture and the real table really are the same rows")
        A("there, so the checksum is comparing data and not merely always differing.")
        A("")
    A("## How to read this")
    A("")
    A("Every model is measured on two independently built legs. Four things are")
    A("compared per model: row count, column names, canonical column types and one")
    A("order-independent checksum per column (plus a null count and a distinct count).")
    A("")
    if real:
        A("Both legs read the same input rows: the real")
        A("`bigquery-public-data.thelook_ecommerce`, read in place by BigQuery and copied")
        A("into `dev.duckdb` by `scripts/load_duckdb_real_sources.sh`. Gating is column")
        A("names and canonical types"
          + (", and with `--same-data` row counts and every per-column checksum, null"
             " count and distinct count too." if args.same_data else
             "; rows and values are reported (`--same-data` makes them gate)."))
        A("")
    else:
        A("Gating (a mismatch exits non-zero) is **column names** and **canonical column")
        A("types**: the part of \"the same data\" that must hold whatever rows the legs")
        A("read. Row counts and checksums are reported but do not gate by default, because")
        A("the two legs deliberately read *different source data* today - the DuckDB target")
        A("reads the deterministic local fixture, the BigQuery target reads the real")
        A("`bigquery-public-data.thelook_ecommerce`. `--same-data` makes them gate too.")
        A("")
    A("## The legs")
    A("")
    A(f"* DuckDB: the materialised `dev.duckdb` (schema `main`), read with the "
      f"`duckdb` CLI.")
    if report.get("bq_source") == "materialised":
        A(f"* BigQuery: the relations `dbt build --target bigquery` materialised in "
          f"`{report.get('bq_relation')}` were measured directly"
          + (f" (build exit {bq['exit']})." if bq.get("exit") is not None
             else " (`--skip-build`: as last built)."))
    elif bq.get("exit") == 0:
        A("* BigQuery: `dbt build --target bigquery` succeeded; models were measured "
          "through the compiled DAG.")
    elif bq.get("exit") is not None:
        A(f"* BigQuery: `dbt build --target bigquery` **failed** (exit {bq['exit']}):")
        A("")
        for ln in (bq.get("first_error", "") or "").splitlines():
            A(f"      {ln}")
        A("")
        ds = report["legs"].get("bigquery_dataset") or {}
        if ds.get("code") == 404:
            A(f"  The target dataset `{args.project}.{SCHEMA}` does not exist"
              " (checked read-only just now: HTTP 404), so nothing can be"
              " materialised. A direct `datasets.create` call by this account is"
              " denied with `403 ... User does not have bigquery.datasets.create"
              f" permission in project {args.project}` (recorded on card t_52340fa8;"
              " this harness only ever reads, so it does not retry the write).")
            A("")
        A("  The harness then compiled the same DAG read-only (every layer ephemeral,")
        A("  so each model is one self-contained query) and ran it. No dataset is")
        A("  written, so no `bigquery.datasets.create` permission is needed - but the")
        A("  materialised BigQuery build itself still cannot run on this machine,")
        A("  which is why `make bq` still exits non-zero.")
    else:
        A(f"* BigQuery: **not measured**. {report['legs'].get('bigquery_error', '')}")
    A("")
    sc = report.get("self_check") or {}
    if sc:
        A(f"## Digest self-check: {'PASS' if sc.get('match') else 'FAIL'}")
        A("")
        A("Both engines render a fixture of constants (int, float, bool, date,")
        A("timestamp, string, decimal) through the same canonical rules and hash it.")
        A("Identical digests prove the checksum is portable rather than assumed to be.")
        A("")
        A("| value | DuckDB | BigQuery |")
        A("|---|---|---|")
        for k in sorted(sc.get("duckdb", {})):
            A(f"| {k} | {sc['duckdb'][k]} | {sc['bigquery'].get(k)} |")
        A("")
    base = report.get("baseline") or {}
    if base.get("ran"):
        A(f"## DuckDB-vs-DuckDB baseline: "
          f"{'MATCH' if base.get('match') else 'MISMATCH'}")
        A("")
        A("`dev.duckdb` was rebuilt from scratch (fixture + `dbt build`) and every"
          if not real else
          "`dev.duckdb`'s models were rebuilt (`dbt build`, same loaded rows) and every")
        A("measurement repeated. This is the sanity check that the harness measures a")
        A("deterministic thing: if the engines disagree later, it is a real difference")
        A("and not harness noise.")
        A("")
    A("## Per model")
    A("")
    timed = "sources" in report
    if timed:
        A("| model | rows (duckdb) | rows (bigquery) | cols | verdict "
          "| duckdb s | bigquery s | bigquery/duckdb |")
        A("|---|---|---|---|---|---|---|---|")
    else:
        A("| model | rows (duckdb) | rows (bigquery) | cols | verdict |")
        A("|---|---|---|---|---|")
    for m in report["models"]:
        rc = m.get("row_count")
        if isinstance(rc, dict):
            rows = f"{rc['duckdb']} | {rc['bigquery']} "
        else:
            rows = f"{rc} | n/a "
        line = f"| {m['model']} | {rows}| {m.get('columns', '')} | {m['verdict']} |"
        if timed:
            d = m.get("duration_s") or {}
            line += (f" {_secs(d.get('duckdb'))} | {_secs(d.get('bigquery'))}"
                     f" | {_ratio(m)} |")
        A(line)
    A("")
    A("## Differences")
    A("")
    ndiff = 0
    for m in report["models"]:
        diffs = m.get("differences") or []
        if not diffs and not m.get("error"):
            continue
        ndiff += 1
        A(f"### {m['model']} - {m['verdict']}")
        A("")
        if m.get("error"):
            A(f"    {m['error']}")
            A("")
            continue
        gating = [d for d in diffs if d["check"] in ("column_names", "column_type")]
        other = [d for d in diffs if d["check"] not in ("column_names", "column_type")]
        if gating:
            A("Gating difference:")
            A("")
            for d in gating:
                A(f"* `{d['check']}`"
                  + (f" on `{d['column']}`" if d.get("column") else "")
                  + f": {d.get('detail', '')}")
            A("")
        if other:
            A(f"{len(other)} reported difference(s)"
              + (" on the same input rows:" if real else
                 " (not gating while the legs read different source data):"))
            A("")
            for d in other[:8]:
                A(f"* `{d['check']}`"
                  + (f" on `{d['column']}`" if d.get("column") else "")
                  + f": duckdb `{d['duckdb']}` vs bigquery `{d['bigquery']}`")
            if len(other) > 8:
                A(f"* ... and {len(other) - 8} more (full list in parity-report.json)")
            A("")
    if not ndiff:
        A("None. Every model matched on every check.")
        A("")
    A("## TRAPS, each with its decision")
    A("")
    A("1. **BIGNUMERIC arrives as VARCHAR.** DuckDB DECIMAL stops at 38 digits, so a")
    A("   wider value is carried as text. The canonical types then read")
    A("   `bignumeric` (BigQuery) vs `string` (DuckDB) and the raw types in")
    A("   `parity-report.json` name it; nothing is widened to hide it.")
    A("2. **NUMERIC(38,9) survives; arithmetic that leaves 38 digits rounds.** Types")
    A("   are compared by *kind*, not precision, because the engines declare different")
    A("   precision for the same number (DuckDB `DECIMAL(18,2)` vs BigQuery")
    A("   `NUMERIC`). Both raw type strings are always recorded.")
    A("3. **Floating point** is compared as integer micro-units")
    A("   (`CAST(ROUND(x * 1000000) AS BIGINT)`), not as text and not with a widened")
    A("   tolerance. One rule, both engines.")
    A("4. **TIMESTAMP vs TIMESTAMPTZ**: compared as *instants* - DuckDB `epoch_us`,")
    A("   BigQuery `UNIX_MICROS` - microseconds since the epoch in UTC. A DuckDB")
    A("   timestamp that keeps a non-UTC offset and a BigQuery timestamp normalised to")
    A("   UTC agree exactly when they are the same instant.")
    A("5. **Arrays and structs** are compared structurally: arrays are sorted and")
    A("   joined with `|`, structs are rendered field by field through the same rules,")
    A("   recursively. No union is compared as raw JSON.")
    A("6. **NULLS ordering and row order**: no metric in this harness depends on row")
    A("   order. Every metric is an aggregate and the checksum is a SUM of per-row")
    A("   hashes. The only sort is inside an array's own values, the same on both")
    A("   engines, so the order a view happens to return rows in never matters.")
    A("7. **NULLs**: a SUM skips NULL rows, so every column also carries an explicit")
    A("   null count and a distinct count; an all-NULL column cannot masquerade as")
    A("   all-zero.")
    A("")
    A("## Reproduce")
    A("")
    A("```bash")
    A("make parity                     # or: python3 scripts/parity.py")
    A("python3 scripts/parity.py --same-data   # gate on rows and checksums too")
    A("```")
    A("")
    A("The BigQuery leg is read-only. It needs a service-account key file, found via")
    A("`BQ_KEYFILE` (the same variable `profiles.yml` uses) and the `openssl` CLI. It")
    A("never writes a dataset, so it works even where")
    A("`bigquery.datasets.create` is denied.")
    A("")
    (REPO / "parity-report.md").write_text("\n".join(lines))


if __name__ == "__main__":
    sys.exit(main())
