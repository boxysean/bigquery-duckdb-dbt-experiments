#!/usr/bin/env python3
"""Parity harness: prove - not assume - that Spark and BigQuery produce the same data.

    make parity                         # Spark vs BigQuery, --same-data (the default)
    python3 scripts/parity.py           # same thing, directly
    python3 scripts/parity.py --self-check   # only the digest-portability step

SPEC.md section 6. Modelled on the root project's scripts/parity.py (DuckDB vs
BigQuery); the per-column pattern and the TRAPS reasoning are carried over, the
DuckDB leg is replaced by a Spark leg. For every model, across two independently
computed legs, it compares:

  * row count,
  * column names,
  * column types (through a canonical cross-engine vocabulary, see TRAPS below),
  * one order-independent checksum per column,
  * a per-column null count and distinct count (they catch what a checksum can't),
  * the model's compiled SQL is the *same model* on both sides by construction.

Before any model it measures the seven SOURCE tables the same way (the "same-data
premise"): the Spark leg reads the Parquet snapshot scripts/load_spark_sources.py
pulled, the BigQuery leg reads bigquery-public-data.thelook_ecommerce live. If the
two inputs already differ, a model difference is drift, not an engine difference,
and the report says so instead of blaming the engine.

Outputs, in the project root (bigquery_spark/):

  parity-report.md     human readable: verdict, the money prediction, one row per
                       model, every difference, the TRAPS section
  parity-report.json   the same content, machine readable

Exit status
  0  parity established: the digest self-check passed, the sources are the same rows,
     and every model matched on every gating check
  1  a real mismatch: a column name, a canonical type, or (with --same-data, the
     default) a row count / checksum / null count / distinct count differs, or the
     two legs' sources are not the same rows, or the digest self-check disagrees
  2  a leg could not be measured (no BigQuery credential, no Spark Thrift Server,
     the sources not loaded into Spark, a compile that failed, a model one engine
     could not run); the report names the leg and the reason. Never a silent pass.
     A real mismatch (1) wins over 2.

GATING
  --same-data is the DEFAULT here: both legs read the same real rows by construction
  (the root project needed `make value-parity` for that; here it is the only mode),
  so row counts and every per-column checksum, null count and distinct count gate as
  well as names and types. --no-same-data reports them without gating.

HOW EACH LEG IS MEASURED (read-only on both; nothing is built or written)
  Both legs measure the SAME compiled DAG: the project is compiled once per target
  with every layer ephemeral, so each model is one self-contained SELECT reading
  only the sources. No dbt build is needed and nothing can be stale.
  * BigQuery: the jobs.query REST API with a service-account JWT (as the root
    harness); schemas from a dry run (0 bytes), metrics capped by
    BQ_MAXIMUM_BYTES_BILLED (1 GB per query by default).
  * Spark: SQL sent to the running Thrift Server with beeline
    (jdbc:hive2://127.0.0.1:10000); schemas from DESCRIBE QUERY, metrics as one
    aggregate row. --spark-source materialised measures the relations
    `dbt build --target spark` wrote to bq_spark_experiments.<model> instead.

TRAPS (each one is a decision, not a shrug)
  1. BIGNUMERIC. Spark DECIMAL tops out at precision 38 (measured), so a BIGNUMERIC
     cannot exist on the Spark leg at all: decimal_type(p > 38) raises a compiler
     error there by design. If one ever appears, the canonical type says
     `bignumeric` vs whatever Spark produced, and the report names it.
  2. NUMERIC vs DECIMAL(18,2). Canonical types compare the *kind* (decimal ==
     numeric), never the precision, because the engines declare different precisions
     for the same column: Spark DECIMAL(18,2) vs BigQuery NUMERIC (38,9). Both raw
     type strings are always in the report. The *values* are compared exactly (after
     dropping trailing fractional zeros, because Spark prints a decimal at its
     declared scale and BigQuery in the shortest form) - which is exactly where the
     money prediction (SPEC 6) shows up or does not.
  3. Floating point. Never compared as text and never with a widened tolerance:
     both sides render the value as `ROUND(x * 1000000)` micro-units, an integer,
     then hash it. One rule, identical on both engines.
  4. TIMESTAMP vs TIMESTAMP_NTZ. Compared as *instants*: Spark `unix_micros(x)`,
     BigQuery `UNIX_MICROS(x)`, microseconds since the epoch. A Spark TIMESTAMP is an
     instant (session time zone UTC, verified by the self-check); TIMESTAMP_NTZ is a
     separate canonical kind (`timestamp_ntz`, BigQuery's DATETIME), so an instant
     on one side and a wall-clock on the other is a gating type difference.
  5. Arrays and structs. Compared structurally, not textually: an array is sorted
     and joined with '|', a struct is rendered field by field through the same
     canonical rules, recursively. A NULL array or struct renders as NULL on both
     engines, so it is never conflated with an empty one. dbt-oss 2.0.5's spark
     adapter cannot even fetch an ARRAY column, and this harness never asks for one: every value is canonicalised
     to a scalar in SQL and only aggregates leave the engine.
  6. NULLS ordering / row order. Nothing depends on row order: every metric is an
     aggregate, the checksum is a SUM of per-row hashes over a canonicalised value,
     and the one sort (inside an array) sorts the *values*, the same on both engines.
  7. NULLs themselves. A SUM over a column ignores NULL rows, so every column also
     carries an explicit null count and a distinct count; a column that is all-NULL
     on one side cannot slip through as "0 == 0".
  8. The live dataset. BigQuery reads the public dataset as it is now; Spark reads a
     snapshot. It changes (orders read 124,952 rows once and 124,650 on 2026-10-06),
     so the sources are compared first and drift is reported as drift.

The checksum is deliberately a portable construction rather than each engine's
native hash: `hash()`/`xxhash64()` on Spark and `FARM_FINGERPRINT()` on BigQuery are
different algorithms. Both engines compute `md5(<canonical text>)`, take the first 8
hex digits as an unsigned 32-bit integer and SUM it (Spark: `conv(..., 16, 10)`,
BigQuery: `CAST('0x...' AS INT64)`). SUM (not XOR) so that a duplicated row changes
the answer; 32 bits so that even 2^31 rows cannot overflow a signed 64-bit sum. Every
run begins by rendering that construction - the production code path, schema
discovery included - over a fixture of constants (every kind: int, float, bool,
date, timestamp, string, decimal, array, struct, and NULLs) on both engines, and
refuses to measure anything if the two disagree (`--self-check` runs just that step).

THE MONEY PREDICTION (SPEC 6), answered explicitly in the report
  money_type() is DECIMAL(18,2) on Spark - exact to its declared scale - and NUMERIC
  (nine decimals) on BigQuery; the root project found exactly that class of
  difference between DuckDB and BigQuery. For every decimal column whose checksum,
  null or distinct count differs, the harness fetches (primary key, value) from both
  legs and counts the differing rows exactly, with the largest difference and
  whether the Spark value is BigQuery's value rounded to two decimals.
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures as cf
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent          # bigquery_spark/
DBT = REPO.parent / ".venv" / "bin" / "dbt"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_portability import strip_sql_comments  # noqa: E402  (same directory)

BQ_API = "https://bigquery.googleapis.com/bigquery/v2/projects/{project}/queries"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = ("https://www.googleapis.com/auth/bigquery "
         "https://www.googleapis.com/auth/cloud-platform")
DEFAULT_KEYFILE = Path.home() / ".config" / "gcp" / "coreychimpbot-sa.json"

SPARK_PREFIX = Path(os.environ.get("SPARK_PREFIX", Path.home() / ".local" / "spark"))
BEELINE = SPARK_PREFIX / "venv" / "bin" / "beeline"
SPARK_HOST = "127.0.0.1"
SPARK_PORT = int(os.environ.get("SPARK_PORT", "10000"))
JDBC_URL = f"jdbc:hive2://{SPARK_HOST}:{SPARK_PORT}/default"
SPARK_USER = "hermes"                  # profiles.yml `user:`
SPARK_SCHEMA = "bq_spark_experiments"  # profiles.yml spark `schema:`

DATA_PROJECT = "bigquery-public-data"
SOURCE_DATASET = "thelook_ecommerce"   # Spark database and BigQuery dataset alike
SOURCES = ["distribution_centers", "products", "users", "inventory_items", "orders",
           "order_items", "events"]

HEX_DIGITS = 8          # 32 bits; 2^32 * 2^31 rows < 2^63, so a SUM cannot overflow
MAX_BYTES = int(os.environ.get("BQ_MAXIMUM_BYTES_BILLED", "1000000000"))
SPARK_WORKERS = 2       # concurrent beeline sessions (the box has 3 cores)
BQ_WORKERS = 4

EXIT_OK, EXIT_MISMATCH, EXIT_UNMEASURED = 0, 1, 2


# --------------------------------------------------------------------------- io
def log(msg: str = "") -> None:
    print(msg, flush=True)


def dbt_env(key=None) -> dict:
    env = dict(os.environ)
    env["DBT_PROFILES_DIR"] = str(REPO)
    env["DBT_ALLOW_EXPERIMENTAL_ADAPTERS"] = "true"
    if key:
        # profiles.yml defaults to `method: oauth`, which ignores `keyfile:`.
        env.setdefault("BQ_KEYFILE", key)
        env.setdefault("BQ_AUTH_METHOD", "service-account")
    return env


def run(cmd, cwd=None, env=None, timeout=1800):
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True,
                          timeout=timeout)


class Unmeasurable(Exception):
    """A leg (or one model on a leg) could not be measured: exit 2, never a pass."""


# ------------------------------------------------------------------- type models
def _split_top(body: str, sep=","):
    """Split on `sep` at nesting depth 0 of <...> and (...)."""
    parts, depth, buf = [], 0, ""
    for ch in body:
        if ch in "<(":
            depth += 1
        elif ch in ">)":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append(buf)
            buf = ""
        else:
            buf += ch
    if buf.strip():
        parts.append(buf)
    return [p.strip() for p in parts]


def spark_kind(type_str: str):
    """Spark type string (DESCRIBE / typeof spelling) -> canonical kind tuple."""
    t = type_str.strip()
    u = t.lower()
    if u.startswith("array<") and u.endswith(">"):
        return ("array", spark_kind(t[6:-1]))
    if u.startswith("struct<") and u.endswith(">"):
        fields = []
        for f in _split_top(t[7:-1]):
            name, _, ftype = f.partition(":")
            fields.append((name.strip().strip("`"), spark_kind(ftype)))
        return ("struct", fields)
    if u.startswith("map<"):
        return ("unknown", t)
    if u in ("tinyint", "smallint", "int", "integer", "bigint", "long", "short", "byte"):
        return ("int",)
    if u in ("double", "float", "real"):
        return ("float",)
    if u == "boolean":
        return ("bool",)
    if u == "date":
        return ("date",)
    if u in ("timestamp", "timestamp_ltz"):
        return ("timestamp",)
    if u == "timestamp_ntz":
        return ("timestamp_ntz",)
    if u == "string" or u.startswith("varchar") or u.startswith("char"):
        return ("string",)
    if u.startswith("decimal") or u.startswith("numeric"):
        return ("decimal",)
    if u == "binary":
        return ("bytes",)
    return ("unknown", t)


def bq_kind(field: dict):
    """BigQuery schema field -> canonical kind tuple."""
    t = (field.get("type") or "").upper()
    base = {
        "INTEGER": ("int",), "INT64": ("int",),
        "FLOAT": ("float",), "FLOAT64": ("float",),
        "BOOLEAN": ("bool",), "BOOL": ("bool",),
        "DATE": ("date",),
        "TIMESTAMP": ("timestamp",), "DATETIME": ("timestamp_ntz",),
        "STRING": ("string",),
        "NUMERIC": ("decimal",), "DECIMAL": ("decimal",),
        "BIGNUMERIC": ("bignumeric",), "BIGDECIMAL": ("bignumeric",),
        "BYTES": ("bytes",),
        # The loader carries GEOGRAPHY as WKT text (what the BigQuery Storage API
        # delivers); it is compared as ST_ASTEXT(x). Raw types stay in the report.
        "GEOGRAPHY": ("geography",),
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
        "timestamp": "timestamp", "timestamp_ntz": "timestamp_ntz", "string": "string",
        "decimal": "decimal", "bignumeric": "bignumeric", "bytes": "bytes",
        "geography": "string",   # WKT text on both legs; raw type GEOGRAPHY is reported
    }.get(k, f"unknown({kind[1] if len(kind) > 1 else '?'})")


# ------------------------------------------------------- canonical SQL rendering
# Spark is a Java regex (`$1`), BigQuery RE2 (`\1`). `[.]` instead of `\.` so neither
# engine's string-literal escaping is involved.
TRAILING_ZEROS = r"([.][0-9]*[1-9])0+$|[.]0+$"


class Engine:
    """Per-engine SQL spellings for the canonical rendering of one value."""

    def __init__(self, name):
        assert name in ("spark", "bigquery")
        self.name = name
        self.bq = name == "bigquery"

    def quote(self, ident):
        return f"`{ident}`"     # both engines quote identifiers with backticks

    def md5_hex(self, expr):
        return f"TO_HEX(MD5({expr}))" if self.bq else f"md5({expr})"

    def hex_to_int(self, hex_expr):
        # first 8 hex digits -> unsigned 32-bit integer, as a 64-bit int
        if self.bq:
            return f"CAST(CONCAT('0x', SUBSTR({hex_expr}, 1, {HEX_DIGITS})) AS INT64)"
        return f"CAST(conv(substr({hex_expr}, 1, {HEX_DIGITS}), 16, 10) AS BIGINT)"

    def to_text(self, expr):
        return f"CAST({expr} AS STRING)"   # STRING on both

    def canon(self, expr, kind, depth=0) -> str:
        """A text rendering of `expr` that is identical on both engines."""
        k = kind[0]
        if k in ("int", "bool", "date"):
            return self.to_text(expr)
        if k == "decimal":
            # Spark prints a decimal at its declared scale (DECIMAL(18,2) 12.30 ->
            # '12.30', 0 -> '0.00'); BigQuery NUMERIC prints the shortest form
            # ('12.3', '0'). Measured. Both sides drop trailing fractional zeros
            # (and a bare '.'); integers are untouched. Values are NOT rounded.
            if self.bq:
                return (f"REGEXP_REPLACE({self.to_text(expr)}, "
                        f"r'{TRAILING_ZEROS}', r'\\1')")
            return f"regexp_replace({self.to_text(expr)}, '{TRAILING_ZEROS}', '$1')"
        if k == "bignumeric":
            return self.to_text(expr)
        if k == "timestamp":
            return self.to_text(f"UNIX_MICROS({expr})" if self.bq else f"unix_micros({expr})")
        if k == "timestamp_ntz":
            # wall clock read as UTC on both (BigQuery TIMESTAMP(datetime) is UTC; the
            # Spark session is UTC, verified by the self-check)
            return self.to_text(f"UNIX_MICROS(TIMESTAMP({expr}))" if self.bq
                                else f"unix_micros(CAST({expr} AS TIMESTAMP))")
        if k == "float":
            rounded = (f"CAST(ROUND(CAST({expr} AS FLOAT64) * 1000000) AS INT64)" if self.bq
                       else f"CAST(round(CAST({expr} AS DOUBLE) * 1000000) AS BIGINT)")
            return self.to_text(rounded)
        if k == "string":
            return self.to_text(expr) if self.bq else expr
        if k == "geography":
            return f"ST_ASTEXT({expr})"
        if k == "bytes":
            return f"TO_HEX({expr})" if self.bq else f"lower(hex({expr}))"
        if k == "array":
            # A NULL array renders as NULL on both engines, never as '' (BigQuery's
            # UNNEST(NULL) yields zero rows, which would conflate it with an empty
            # array); the explicit guard keeps the two engines the same shape.
            var = f"__e{depth}"
            rendered = self.canon(var, kind[1], depth + 1)
            if self.bq:
                return (f"CASE WHEN {expr} IS NULL THEN NULL ELSE "
                        f"ARRAY_TO_STRING(ARRAY(SELECT {rendered} AS c "
                        f"FROM UNNEST({expr}) AS {var} ORDER BY c), '|') END")
            return (f"CASE WHEN {expr} IS NULL THEN NULL ELSE "
                    f"array_join(array_sort(transform({expr}, {var} -> {rendered})), '|') END")
        if k == "struct":
            # a NULL struct renders as NULL, not as a struct of NULLs
            parts = [f"COALESCE({self.canon(f'{expr}.{self.quote(n)}', t, depth + 1)}, '<null>')"
                     for n, t in kind[1]]
            if self.bq:
                return (f"CASE WHEN {expr} IS NULL THEN NULL ELSE "
                        + (" || '|' || ".join(parts) or "''") + " END")
            return (f"CASE WHEN {expr} IS NULL THEN NULL ELSE "
                    "concat_ws('|', " + ", ".join(parts) + ") END")
        return self.to_text(expr)


def metric_names(columns):
    """The metric keys, in the order metrics_sql selects them."""
    out = ["__rows"]
    for name, _kind in columns:
        out += [f"{name}__nulls", f"{name}__sum", f"{name}__distinct"]
    return out


def metrics_sql(engine: Engine, source: str, columns) -> str:
    """One row: the row count plus three aggregates per column."""
    parts = ["COUNT(*) AS __rows"]
    for i, (name, kind) in enumerate(columns):
        col = engine.quote(name)
        text = engine.canon(col, kind)
        parts.append(f"SUM(CASE WHEN {col} IS NULL THEN 1 ELSE 0 END) AS m{i}__nulls")
        parts.append(f"SUM({engine.hex_to_int(engine.md5_hex(text))}) AS m{i}__sum")
        parts.append(f"COUNT(DISTINCT {text}) AS m{i}__distinct")
    return "SELECT " + ",\n  ".join(parts) + "\nFROM " + source


def _normalise(values, columns) -> dict:
    """Positional metric values -> {metric: int}, with SUM(NULL) -> 0."""
    names = metric_names([(c[0], c[1]) for c in columns])
    if len(values) != len(names):
        raise RuntimeError(f"expected {len(names)} metrics, got {len(values)}")
    return {n: (0 if v in (None, "", "NULL") else int(v)) for n, v in zip(names, values)}


# ------------------------------------------------------------------- Spark leg
class SparkLeg:
    name = "spark"
    engine = Engine("spark")

    def __init__(self):
        self._env = None

    def problem(self):
        """None when the endpoint and beeline are usable, else the reason."""
        if not BEELINE.exists():
            return f"beeline not found at {BEELINE} (run scripts/install_prereqs.sh)"
        try:
            with socket.create_connection((SPARK_HOST, SPARK_PORT), timeout=3):
                pass
        except OSError:
            return (f"no Spark Thrift Server on {SPARK_HOST}:{SPARK_PORT}"
                    " (run scripts/start_spark.sh)")
        return None

    @property
    def env(self):
        if self._env is None:
            py = SPARK_PREFIX / "venv" / "bin" / "python"
            home = run([str(py), "-c", "import os, pyspark; "
                        "print(os.path.dirname(pyspark.__file__))"]).stdout.strip()
            self._env = dict(os.environ, JAVA_HOME=str(SPARK_PREFIX / "jdk"), SPARK_HOME=home)
        return self._env

    def _beeline(self, statements):
        """Run statements in one beeline session; returns (stdout, stderr, rc).

        tsv2 without a header is the clean format: csv2 prefixes each result set
        after the first with a carriage-return progress artefact and quotes with NUL
        (measured). Statements are separated by marker rows so the output can be
        split; --force keeps going after a failed statement.
        """
        body = []
        for i, st in enumerate(statements):
            st = strip_sql_comments(st).strip().rstrip(";")
            if ";" in st:
                # beeline splits a file on ';'; one inside a string literal would cut
                # a statement in two. None of this project's models has one.
                raise RuntimeError("a ';' survived comment stripping; beeline would split it")
            body.append(f"SELECT '@@BEGIN {i}';")
            body.append(st + ";")
        body.append(f"SELECT '@@BEGIN {len(statements)}';")
        with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False) as f:
            f.write("\n".join(body) + "\n")
            path = f.name
        try:
            # bytes, not text: text mode would turn the artefact's '\r' into newlines
            out = subprocess.run([str(BEELINE), "-u", JDBC_URL, "-n", SPARK_USER,
                                  "--silent=true", "--showHeader=false", "--outputformat=tsv2",
                                  "--force=true", "-f", path],
                                 env=self.env, capture_output=True, timeout=3600)
        finally:
            os.unlink(path)
        # beeline draws a progress line between statements and erases it with
        # carriage returns: '\rnull<spaces>\rnull', glued to the next line (measured).
        stdout = re.sub(r"\rnull *\rnull", "", out.stdout.decode("utf-8", "replace"))
        return stdout, out.stderr.decode("utf-8", "replace"), out.returncode

    def query_many(self, statements):
        """[rows (list of list of str)] or an Exception, one per statement."""
        stdout, stderr, _rc = self._beeline(statements)
        sections, current = {}, None
        for line in stdout.split("\n"):
            m = re.fullmatch(r"@@BEGIN (\d+)", line.strip())
            if m:
                current = int(m.group(1))
                sections[current] = []
                continue
            if current is not None and line != "":
                sections[current].append(line.split("\t"))
        errors = [l for l in stderr.splitlines() if l.startswith("Error:")]
        results = []
        for i in range(len(statements)):
            if i not in sections:
                results.append(RuntimeError("beeline produced no output for the statement"
                                            + (f": {errors[0][:600]}" if errors else "")))
            elif sections[i] == [] and i + 1 in sections and errors:
                results.append(RuntimeError(errors.pop(0)[:600]))
            else:
                results.append(sections[i])
        if len(statements) == 1 and isinstance(results[0], list) and not results[0] and errors:
            results[0] = RuntimeError(errors[0][:600])
        return results

    def query(self, statement):
        res = self.query_many([statement])[0]
        if isinstance(res, Exception):
            raise res
        return res

    def schema_of(self, source):
        """[(name, kind, raw type)] of anything a FROM accepts."""
        return self._parse_describe(self.query(f"DESCRIBE QUERY SELECT * FROM {source}"))

    @staticmethod
    def _parse_describe(rows):
        cols = []
        for r in rows:
            if not r or not r[0] or r[0].startswith("#"):
                break
            cols.append((r[0], spark_kind(r[1]), r[1]))
        if not cols:
            raise RuntimeError("DESCRIBE returned no columns")
        return cols

    def measure_of(self, source, columns):
        rows = self.query(metrics_sql(self.engine, source, [(n, k) for n, k, _ in columns]))
        if len(rows) != 1:
            raise RuntimeError(f"expected one metrics row, got {len(rows)}")
        return _normalise(rows[0], columns)

    def scalar(self, sql):
        return self.query(sql)[0][0]


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
        self.bytes_billed = 0

    @property
    def token(self):
        if self._token is None:
            self._token = access_token(self.key)
        return self._token

    def _call(self, req):
        req.add_header("Authorization", "Bearer " + self.token)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=900) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"BigQuery HTTP {e.code}: {e.read().decode()[:600]}")

    def query(self, sql: str, dry_run=False):
        """(schema fields, rows as list-of-list-of-text), every page.

        jobs.query answers `jobComplete: false` after its timeoutMs and the job keeps
        running (the root harness measured that); an incomplete answer, and every
        further page, is fetched with getQueryResults.
        """
        body = {"query": sql, "useLegacySql": False, "maximumBytesBilled": str(MAX_BYTES),
                "timeoutMs": 60000, "dryRun": dry_run}
        out = self._call(urllib.request.Request(BQ_API.format(project=self.project),
                                                data=json.dumps(body).encode()))
        if dry_run:
            return out.get("schema", {}).get("fields", []), []
        ref = out["jobReference"]
        deadline = time.time() + 1800
        rows = [r.get("f", []) for r in out.get("rows", [])] if out.get("jobComplete") else []
        page = out.get("pageToken")
        while not out.get("jobComplete", True) or page:
            if time.time() > deadline:
                raise RuntimeError("BigQuery job did not complete within 1800 s")
            params = {"location": ref.get("location", ""), "timeoutMs": 60000}
            if page:
                params["pageToken"] = page
            out = self._call(urllib.request.Request(
                f"{BQ_API.format(project=self.project)}/{ref['jobId']}?"
                + urllib.parse.urlencode(params)))
            if out.get("jobComplete"):
                rows += [r.get("f", []) for r in out.get("rows", [])]
                page = out.get("pageToken")
        self.bytes_billed += int(out.get("totalBytesBilled") or 0)
        fields = out.get("schema", {}).get("fields", [])
        return fields, [[c.get("v") for c in r] for r in rows]

    def schema_of(self, source):
        fields, _ = self.query(f"SELECT * FROM {source}", dry_run=True)
        if not fields:
            raise RuntimeError("the dry run returned no schema")
        return [(f["name"], bq_kind(f), _bq_type_str(f)) for f in fields]

    def measure_of(self, source, columns):
        _, rows = self.query(metrics_sql(self.engine, source,
                                         [(n, k) for n, k, _ in columns]))
        return _normalise(rows[0], columns)


def _bq_type_str(field):
    t = field["type"]
    if t == "RECORD":
        t = "STRUCT<" + ", ".join(f"{c['name']} {_bq_type_str(c)}"
                                  for c in field.get("fields", [])) + ">"
    if (field.get("mode") or "").upper() == "REPEATED":
        return f"ARRAY<{t}>"
    return t


# ------------------------------------------------------------- digest self-check
# One fixture of constants per engine, the same values spelled in each dialect. Rows
# carry every canonical kind, values that print differently on the two engines
# (12.30 / 12.00 / 0.00 decimals, a float that is not exact in binary, a timestamp
# with microseconds, a non-ASCII string, an unsorted array) and one all-NULL row.
_FIXTURE = [
    # i, f, b, d, ts, s, dec, arr, (struct a, struct b)
    ("1", "1.5", "true", "2024-03-15", "2024-03-15 13:45:12.123456", "abc", "12.34",
     ["3", "1", "2"], ("1", "x")),
    ("2", "-2.25", "false", "2023-01-01", "2023-01-01 00:00:00", "ABC", "-0.05",
     ["10", "9"], ("2", "")),
    ("3", "0.30000000000000004", "true", "2024-02-29", "2024-02-29 23:59:59.999999", "Zürich",
     "12.30", [], ("3", "z")),
    ("4", "100.0", "false", "1999-12-31", "1999-12-31 12:00:00", "", "12.00", ["7"], ("4", "y")),
    ("5", "0.0000001", "true", "1970-01-01", "1970-01-01 00:00:00", "x|y", "0.00",
     ["1", "1"], ("5", "w")),
    ("6", "2.0", "true", "2020-06-01", "2020-06-01 00:00:00", "n", "1.00",
     ["9", "NULL"], ("6", "v")),   # an array with a NULL element
    None,   # every column NULL
]


def fixture_sql(engine: Engine) -> str:
    bq = engine.bq
    selects = []
    for row in _FIXTURE:
        if row is None:
            if bq:
                vals = ["CAST(NULL AS INT64)", "CAST(NULL AS FLOAT64)", "CAST(NULL AS BOOL)",
                        "CAST(NULL AS DATE)", "CAST(NULL AS TIMESTAMP)", "CAST(NULL AS STRING)",
                        "CAST(NULL AS NUMERIC)", "CAST(NULL AS ARRAY<INT64>)",
                        "CAST(NULL AS STRUCT<a INT64, b STRING>)"]
            else:
                vals = ["CAST(NULL AS BIGINT)", "CAST(NULL AS DOUBLE)", "CAST(NULL AS BOOLEAN)",
                        "CAST(NULL AS DATE)", "CAST(NULL AS TIMESTAMP)", "CAST(NULL AS STRING)",
                        "CAST(NULL AS DECIMAL(18,2))", "CAST(NULL AS ARRAY<BIGINT>)",
                        "CAST(NULL AS STRUCT<a: BIGINT, b: STRING>)"]
        else:
            i, f, b, d, ts, s, dec, arr, (sa, sb) = row
            if bq:
                vals = [f"CAST({i} AS INT64)", f"CAST({f} AS FLOAT64)", b, f"DATE '{d}'",
                        f"TIMESTAMP '{ts}'", f"'{s}'", f"NUMERIC '{dec}'",
                        ("CAST([] AS ARRAY<INT64>)" if not arr else
                         "[" + ", ".join(f"CAST({x} AS INT64)" for x in arr) + "]"),
                        f"STRUCT(CAST({sa} AS INT64) AS a, '{sb}' AS b)"]
            else:
                vals = [f"CAST({i} AS BIGINT)", f"CAST({f} AS DOUBLE)", b, f"DATE '{d}'",
                        f"TIMESTAMP '{ts}'", f"'{s}'", f"CAST({dec} AS DECIMAL(18,2))",
                        ("CAST(array() AS ARRAY<BIGINT>)" if not arr else
                         "array(" + ", ".join(f"CAST({x} AS BIGINT)" for x in arr) + ")"),
                        f"named_struct('a', CAST({sa} AS BIGINT), 'b', '{sb}')"]
        names = ["i", "f", "b", "d", "ts", "s", "dec", "arr", "st"]
        selects.append("SELECT " + ", ".join(f"{v} AS {n}" for v, n in zip(vals, names)))
    return "(\n" + "\n  UNION ALL ".join(selects) + "\n) AS _fixture"


def digest_selfcheck(spark: SparkLeg, bq: BigQueryLeg):
    """Both engines must agree on schema kinds and every metric for the constants.

    It runs the PRODUCTION code path - schema discovery, kind mapping, Engine.canon,
    metrics_sql - so it verifies what the model measurements will actually use.
    """
    s_src, b_src = fixture_sql(spark.engine), fixture_sql(bq.engine)
    s_cols, b_cols = spark.schema_of(s_src), bq.schema_of(b_src)
    s_kinds = {n: kind_label(k) for n, k, _ in s_cols}
    b_kinds = {n: kind_label(k) for n, k, _ in b_cols}
    s = spark.measure_of(s_src, s_cols)
    b = bq.measure_of(b_src, b_cols)
    tz = spark.scalar("SELECT current_timezone()")
    ok = s == b and s_kinds == b_kinds and tz == "UTC"
    return {"spark": s, "bigquery": b, "kinds": {"spark": s_kinds, "bigquery": b_kinds},
            "raw_types": {"spark": {n: r for n, _, r in s_cols},
                          "bigquery": {n: r for n, _, r in b_cols}},
            "spark_session_time_zone": tz, "match": ok,
            "sql": {"spark": metrics_sql(spark.engine, s_src, [(n, k) for n, k, _ in s_cols]),
                    "bigquery": metrics_sql(bq.engine, b_src, [(n, k) for n, k, _ in b_cols])}}


def print_selfcheck(sc):
    for k in sorted(sc["spark"]):
        s, b = sc["spark"][k], sc["bigquery"].get(k)
        log(f"  {k:16s} spark {s:>16d}   bigquery {b if b is not None else 'n/a':>16}"
            f"   {'ok' if s == b else 'MISMATCH'}")
    for n in sc["kinds"]["spark"]:
        s, b = sc["kinds"]["spark"][n], sc["kinds"]["bigquery"].get(n)
        log(f"  kind {n:11s} spark {s:>24s} ({sc['raw_types']['spark'][n]})   bigquery"
            f" {b} ({sc['raw_types']['bigquery'].get(n)})   {'ok' if s == b else 'MISMATCH'}")
    log(f"  spark session time zone: {sc['spark_session_time_zone']}"
        f"   {'ok' if sc['spark_session_time_zone'] == 'UTC' else 'MISMATCH (must be UTC)'}")


# ------------------------------------------------------------------- comparison
def model_verdict(s_model, b_model):
    """Compare one model on both legs; returns (verdict, differences, gating_by_schema)."""
    diffs = []
    s_names = [c[0] for c in s_model["columns"]]
    b_names = [c[0] for c in b_model["columns"]]
    if s_names != b_names:
        missing = [c for c in s_names if c not in b_names]
        extra = [c for c in b_names if c not in s_names]
        same_set = sorted(s_names) == sorted(b_names)
        diffs.append({"check": "column_names", "spark": s_names, "bigquery": b_names,
                      "detail": ("same set, different order" if same_set else
                                 f"only in spark: {missing}; only in bigquery: {extra}")})
    s_types = {c[0]: (kind_label(c[1]), c[2]) for c in s_model["columns"]}
    b_types = {c[0]: (kind_label(c[1]), c[2]) for c in b_model["columns"]}
    for name in s_names:
        if name in b_types and s_types[name][0] != b_types[name][0]:
            diffs.append({"check": "column_type", "column": name,
                          "spark": s_types[name][0], "bigquery": b_types[name][0],
                          "detail": f"raw types: spark {s_types[name][1]} vs bigquery"
                                    f" {b_types[name][1]}"})
    sm, bm = s_model["metrics"], b_model["metrics"]
    if sm["__rows"] != bm["__rows"]:
        diffs.append({"check": "row_count", "spark": sm["__rows"], "bigquery": bm["__rows"],
                      "detail": "same input rows, different row count"})
    for name in s_names:
        if name not in b_types:
            continue
        for suffix, label in (("sum", "checksum"), ("nulls", "null_count"),
                              ("distinct", "distinct_count")):
            sv, bv = sm.get(f"{name}__{suffix}"), bm.get(f"{name}__{suffix}")
            if sv != bv:
                diffs.append({"check": f"column_{label}", "column": name,
                              "spark": sv, "bigquery": bv,
                              "kind": s_types[name][0],
                              "detail": "same input rows, different values"})
    gating = any(d["check"] in ("column_names", "column_type") for d in diffs)
    return ("match" if not diffs else "differs"), diffs, gating


# ------------------------------------------------------------------- the driver
def discover_models():
    out = run([str(DBT), "ls", "--quiet", "--target", "spark", "--resource-type", "model",
               "--output", "json", "--output-keys", "name"], cwd=str(REPO), env=dbt_env())
    names = re.findall(r'"name"\s*:\s*"([^"]+)"', out.stdout)
    seen, ordered = set(), []
    for n in names:
        if n not in seen:
            seen.add(n)
            ordered.append(n)
    if not ordered:
        raise RuntimeError("dbt ls found no models:\n" + (out.stdout + out.stderr)[-1500:])
    return ordered


def compile_ephemeral(target: str, key=None):
    """Compile every model of `target` into one self-contained query.

    All layers ephemeral, so `dbt compile` inlines the whole DAG as `__dbt__cte__...`
    CTEs and each model becomes a plain SELECT over the sources: read-only on both
    engines, and the same DAG on both, by construction.
    """
    tmp = Path(tempfile.mkdtemp(prefix=f"parity-eph-{target}-"))
    try:
        (tmp / "dbt_project.yml").write_text(
            "name: bq_spark_experiments\n"
            "profile: bq_spark_experiments\n"
            'model-paths: ["models"]\n'
            'macro-paths: ["macros"]\n'
            'test-paths: ["tests"]\n'
            "models:\n"
            "  bq_spark_experiments:\n"
            "    +static_analysis: strict\n"
            "    staging:\n      +materialized: ephemeral\n"
            "    intermediate:\n      +materialized: ephemeral\n"
            "    marts:\n      +materialized: ephemeral\n")
        for d in ("models", "macros", "tests"):
            os.symlink(REPO / d, tmp / d)
        out = run([str(DBT), "compile", "--target", target, "--project-dir", str(tmp)],
                  cwd=str(REPO), env=dbt_env(key))
        if out.returncode != 0:
            raise RuntimeError(f"dbt compile --target {target} (ephemeral) exit"
                               f" {out.returncode}:\n" + (out.stdout + out.stderr)[-2000:])
        compiled = {}
        for path in (tmp / "target" / "compiled").rglob("models/**/*.sql"):
            compiled[path.stem] = path.read_text()
        return compiled
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def model_keys():
    """{model: primary-key column}, from the column-level `unique` tests in the YAML."""
    import yaml
    keys = {}
    for yml in (REPO / "models").rglob("*.yml"):
        doc = yaml.safe_load(yml.read_text()) or {}
        for m in doc.get("models", []) or []:
            for c in m.get("columns", []) or []:
                tests = (c.get("data_tests") or []) + (c.get("tests") or [])
                if "unique" in tests and m["name"] not in keys:
                    keys[m["name"]] = c["name"]
    return keys


def layer_of(model: str) -> str:
    for layer in ("staging", "intermediate", "marts"):
        if any((REPO / "models" / layer).rglob(f"{model}.sql")):
            return layer
    return "?"


def measure_leg(leg, items, workers):
    """items: {name: FROM-source}. Returns {name: {columns, metrics, secs} | {error}}."""
    def one(name, source):
        t0 = time.time()
        try:
            cols = leg.schema_of(source)
            return name, {"columns": cols, "metrics": leg.measure_of(source, cols),
                          "secs": round(time.time() - t0, 2)}
        except Exception as e:  # noqa: BLE001
            return name, {"error": str(e)[:1500]}

    out = {}
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(one, n, s) for n, s in items.items()]
        for fut in cf.as_completed(futures):
            name, res = fut.result()
            out[name] = res
            state = (f"{res['metrics']['__rows']:>9,} rows, {len(res['columns'])} cols,"
                     f" {res['secs']:.1f}s" if "metrics" in res else "ERROR " + res["error"].splitlines()[0][:150])
            log(f"      {leg.name:8s} {name:40s} {state}")
    return out


# ------------------------------------------------------------- the money finding
def _dec(text):
    try:
        return None if text in (None, "", "NULL") else Decimal(text)
    except InvalidOperation:
        return None


def money_rows(spark, bq, model, key, columns, s_src, b_src):
    """Exact per-row comparison of decimal columns, joined on the model's key."""
    def select(engine):
        cols = [f"CAST({engine.quote(key)} AS STRING) AS k"]
        cols += [f"{engine.canon(engine.quote(c), ('decimal',))} AS v{i}"
                 for i, c in enumerate(columns)]
        return "SELECT " + ", ".join(cols)

    s_rows = spark.query(f"{select(spark.engine)} FROM {s_src}")
    _, b_rows = bq.query(f"{select(bq.engine)} FROM {b_src}")
    s_map = {r[0]: r[1:] for r in s_rows}
    b_map = {r[0]: r[1:] for r in b_rows}
    out = {}
    for i, c in enumerate(columns):
        differing, rounded, max_diff, examples = 0, 0, Decimal(0), []
        for k in s_map.keys() & b_map.keys():
            sv, bv = _dec(s_map[k][i]), _dec(b_map[k][i])
            if sv == bv:
                continue
            differing += 1
            if sv is not None and bv is not None:
                d = abs(sv - bv)
                max_diff = max(max_diff, d)
                if sv == bv.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP):
                    rounded += 1
            if len(examples) < 3:
                examples.append({"key": k, "spark": s_map[k][i], "bigquery": b_map[k][i]})
        out[c] = {"model": model, "column": c, "key": key, "rows_compared":
                  len(s_map.keys() & b_map.keys()), "differing_rows": differing,
                  "spark_is_bigquery_rounded_to_cents": rounded,
                  "max_abs_difference": str(max_diff), "examples": examples,
                  "keys_only_in_spark": len(s_map.keys() - b_map.keys()),
                  "keys_only_in_bigquery": len(b_map.keys() - s_map.keys())}
    return out


# ------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--same-data", dest="same_data", action="store_true", default=True,
                    help="gate on row counts and checksums too (DEFAULT: both legs read"
                         " the same real rows)")
    ap.add_argument("--no-same-data", dest="same_data", action="store_false",
                    help="report rows and values without gating on them")
    ap.add_argument("--self-check", dest="self_check", action="store_true",
                    help="run only the digest self-check on both engines and exit")
    ap.add_argument("--spark-source", choices=("compiled", "materialised"),
                    default="compiled",
                    help="Spark leg: `compiled` (default; the ephemeral DAG, read-only) or"
                         f" `materialised` ({SPARK_SCHEMA}.<model>, built by"
                         " `dbt build --target spark`)")
    ap.add_argument("--models", help="comma-separated subset (default: every model)")
    ap.add_argument("--project", default=os.environ.get("BQ_BILLING_PROJECT", "coreychimpbot"))
    args = ap.parse_args()
    started = time.time()

    key = os.environ.get("BQ_KEYFILE") or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not key and DEFAULT_KEYFILE.exists():
        key = str(DEFAULT_KEYFILE)
    bq_problem = None
    if not key:
        bq_problem = "no BigQuery credential (set BQ_KEYFILE to a service-account key file)"
    elif not Path(key).is_file():
        bq_problem = "the BigQuery key file named by BQ_KEYFILE does not exist"
    elif not shutil.which("openssl"):
        bq_problem = "openssl is not installed (it signs the service-account JWT)"

    spark = SparkLeg()
    spark_problem = spark.problem()
    bq = BigQueryLeg(key, args.project) if not bq_problem else None
    if bq is not None:
        try:
            bq.token  # fail fast on bad credentials
        except Exception as e:  # noqa: BLE001
            bq_problem = f"the BigQuery credential was refused: {str(e)[:300]}"
            bq = None

    report = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
              "same_data": args.same_data, "spark_source": args.spark_source,
              "legs": {"spark": spark_problem or "ok", "bigquery": bq_problem or "ok"},
              "self_check": {}, "sources": [], "models": [], "money": {}}

    def unmeasured_exit(which, why):
        log(f"\nparity: the {which} leg could not be measured: {why}")
        log("parity: NOT established (exit 2).")
        report["verdict"] = {"exit": EXIT_UNMEASURED, "reason": f"{which}: {why}"}
        write_reports(report)
        return EXIT_UNMEASURED

    # ---------------------------------------------------------------- self-check
    log("[1/5] digest self-check (constants on both engines, production code path)")
    if spark_problem:
        return unmeasured_exit("Spark", spark_problem)
    if bq_problem:
        return unmeasured_exit("BigQuery", bq_problem)
    try:
        sc = digest_selfcheck(spark, bq)
    except Exception as e:  # noqa: BLE001
        return unmeasured_exit("Spark or BigQuery", f"the self-check query failed: {e}")
    report["self_check"] = sc
    print_selfcheck(sc)
    log(f"      digest self-check: {'PASS' if sc['match'] else 'FAIL'}")
    if args.self_check:
        return EXIT_OK if sc["match"] else EXIT_MISMATCH
    if not sc["match"]:
        log("FATAL: the two engines do not agree on the digest construction; any"
            " comparison built on it would be meaningless.")
        report["verdict"] = {"exit": EXIT_MISMATCH, "reason": "digest self-check FAILED"}
        write_reports(report)
        return EXIT_MISMATCH

    # ------------------------------------------------------- same-data premise
    log("\n[2/5] the same-data premise: the seven sources, Spark snapshot vs BigQuery live")
    present = spark.query(f"SHOW TABLES IN {SOURCE_DATASET}") \
        if "thelook_ecommerce" in str(spark.query("SHOW DATABASES")) else []
    have = {r[1] for r in present if len(r) > 1}
    missing = [t for t in SOURCES if t not in have]
    if missing:
        return unmeasured_exit("Spark", f"source table(s) not loaded: "
                               f"{', '.join(SOURCE_DATASET + '.' + t for t in missing)}"
                               " (run make load-sources)")
    s_src = measure_leg(spark, {t: f"{SOURCE_DATASET}.{t}" for t in SOURCES}, SPARK_WORKERS)
    b_src = measure_leg(bq, {t: f"`{DATA_PROJECT}.{SOURCE_DATASET}.{t}`" for t in SOURCES},
                        BQ_WORKERS)
    source_diffs, source_unmeasured = [], []
    for t in SOURCES:
        if "error" in s_src[t] or "error" in b_src[t]:
            source_unmeasured.append(t)
            report["sources"].append({"table": t, "verdict": "not_measured",
                                      "error": s_src[t].get("error") or b_src[t].get("error")})
            continue
        verdict, diffs, _ = model_verdict(s_src[t], b_src[t])
        report["sources"].append({"table": t, "verdict": verdict,
                                  "row_count": {"spark": s_src[t]["metrics"]["__rows"],
                                                "bigquery": b_src[t]["metrics"]["__rows"]},
                                  "columns": [[c[0], kind_label(c[1]), c[2]]
                                              for c in s_src[t]["columns"]],
                                  "bigquery_types": [[c[0], c[2]] for c in b_src[t]["columns"]],
                                  "differences": diffs})
        if diffs:
            source_diffs.append(t)
    log(f"      sources: {len(SOURCES) - len(source_diffs) - len(source_unmeasured)} of"
        f" {len(SOURCES)} identical on every check"
        + (f"; DIFFER: {', '.join(source_diffs)}" if source_diffs else "")
        + (f"; not measured: {', '.join(source_unmeasured)}" if source_unmeasured else ""))
    if source_unmeasured:
        return unmeasured_exit("Spark or BigQuery",
                               f"source(s) could not be measured: {', '.join(source_unmeasured)}")

    # ------------------------------------------------------------------ compile
    log("\n[3/5] compiling the DAG for both targets (every layer ephemeral, read-only)")
    try:
        models = discover_models()
    except Exception as e:  # noqa: BLE001
        return unmeasured_exit("Spark", f"dbt ls failed: {e}")
    if args.models:
        wanted = [m.strip() for m in args.models.split(",") if m.strip()]
        unknown = [m for m in wanted if m not in models]
        if unknown:
            log(f"unknown model(s): {', '.join(unknown)}")
            return EXIT_MISMATCH
        models = wanted
    log(f"      {len(models)} model(s)")
    try:
        b_compiled = compile_ephemeral("bigquery", key)
    except Exception as e:  # noqa: BLE001
        return unmeasured_exit("BigQuery", str(e))
    s_compiled = {}
    if args.spark_source == "compiled":
        try:
            s_compiled = compile_ephemeral("spark")
        except Exception as e:  # noqa: BLE001
            return unmeasured_exit("Spark", str(e))

    def s_from(m):
        if args.spark_source == "materialised":
            return f"{SPARK_SCHEMA}.{m}"
        return f"(\n{s_compiled[m]}\n) AS _m"

    def b_from(m):
        return f"(\n{b_compiled[m]}\n) AS _m"

    # ------------------------------------------------------------------ measure
    log("\n[4/5] measuring every model on both legs")
    s_items = {m: s_from(m) for m in models
               if args.spark_source == "materialised" or m in s_compiled}
    b_items = {m: b_from(m) for m in models if m in b_compiled}
    s_models = measure_leg(spark, s_items, SPARK_WORKERS)
    b_models = measure_leg(bq, b_items, BQ_WORKERS)
    (REPO / "target").mkdir(exist_ok=True)
    for name, leg in (("spark", s_models), ("bigquery", b_models)):
        json.dump({m: ({"error": v["error"]} if "error" in v else
                       {"columns": [[c[0], kind_label(c[1]), c[2]] for c in v["columns"]],
                        "metrics": v["metrics"], "secs": v["secs"]})
                   for m, v in leg.items()},
                  open(REPO / "target" / f"parity-{name}-leg.json", "w"), indent=2)

    gating_failed, value_failed, unmeasured = [], [], []
    for m in models:
        s, b = s_models.get(m), b_models.get(m)
        entry = {"model": m, "layer": layer_of(m)}
        if s is None or b is None or "error" in s or "error" in b:
            why = []
            for leg, res, comp in (("spark", s, s_items), ("bigquery", b, b_items)):
                if res is None:
                    why.append(f"{leg}: not compiled")
                elif "error" in res:
                    why.append(f"{leg}: {res['error']}")
            unmeasured.append(m)
            entry.update({"verdict": "not_measured", "error": "\n".join(why)})
            report["models"].append(entry)
            continue
        verdict, diffs, gated = model_verdict(s, b)
        entry.update({"verdict": verdict,
                      "row_count": {"spark": s["metrics"]["__rows"],
                                    "bigquery": b["metrics"]["__rows"]},
                      "columns": len(s["columns"]),
                      "types": [[c[0], kind_label(c[1]), c[2],
                                 next((x[2] for x in b["columns"] if x[0] == c[0]), None)]
                                for c in s["columns"]],
                      "secs": {"spark": s["secs"], "bigquery": b["secs"]},
                      "differences": diffs})
        report["models"].append(entry)
        if gated:
            gating_failed.append(m)
        elif diffs:
            value_failed.append(m)

    # ------------------------------------------------------- the money finding
    log("\n[5/5] the money prediction: decimal columns, row by row where they differ")
    keys = model_keys()
    money = {"decimal_columns": [], "differing": [], "keyless": []}
    for entry in report["models"]:
        if entry["verdict"] == "not_measured":
            continue
        m = entry["model"]
        decs = [t for t in entry["types"] if t[1] == "decimal"]
        diffcols = {d.get("column") for d in entry["differences"]
                    if d["check"].startswith("column_") and d.get("column")}
        for name, _kind, s_raw, b_raw in decs:
            money["decimal_columns"].append({"model": m, "column": name, "spark_type": s_raw,
                                             "bigquery_type": b_raw,
                                             "checksum_equal": name not in diffcols})
        todo = [t[0] for t in decs if t[0] in diffcols]
        if not todo:
            continue
        key_col = keys.get(m)
        if not key_col:
            money["keyless"].append({"model": m, "columns": todo})
            log(f"      {m}: no unique key in the YAML; {', '.join(todo)} differ"
                " (row count not computable without a key)")
            continue
        try:
            per = money_rows(spark, bq, m, key_col, todo, s_from(m), b_from(m))
        except Exception as e:  # noqa: BLE001
            money["keyless"].append({"model": m, "columns": todo, "error": str(e)[:600]})
            log(f"      {m}: row fetch failed: {str(e)[:200]}")
            continue
        for c, r in per.items():
            money["differing"].append(r)
            log(f"      {m}.{c}: {r['differing_rows']:,} of {r['rows_compared']:,} rows differ"
                f" (max |diff| {r['max_abs_difference']}; Spark == BigQuery rounded to cents"
                f" on {r['spark_is_bigquery_rounded_to_cents']:,})")
    money["prediction_confirmed"] = any(r["differing_rows"] for r in money["differing"]) \
        or bool(money["keyless"])
    report["money"] = money

    # ------------------------------------------------------------------ verdict
    report["bigquery_bytes_billed"] = bq.bytes_billed
    report["wall_s"] = round(time.time() - started, 1)
    if source_diffs and args.same_data:
        code, reason = EXIT_MISMATCH, (f"the same-data premise does not hold: source(s)"
                                       f" {', '.join(source_diffs)} differ between the Spark"
                                       " snapshot and live BigQuery (reload: make load-sources)")
    elif gating_failed or (args.same_data and value_failed):
        code, reason = EXIT_MISMATCH, (f"gating (names/types): {gating_failed or 'none'};"
                                       f" rows/values: {value_failed or 'none'}")
    elif unmeasured:
        code, reason = EXIT_UNMEASURED, f"model(s) not measured: {', '.join(unmeasured)}"
    else:
        code, reason = EXIT_OK, f"all {len(models)} models match on every check"
    report["verdict"] = {"exit": code, "reason": reason, "gating_failed": gating_failed,
                         "value_failed": value_failed, "unmeasured": unmeasured,
                         "source_diffs": source_diffs}
    write_reports(report)
    n_match = sum(1 for e in report["models"] if e["verdict"] == "match")
    log(f"\nparity: {n_match} of {len(models)} models match on every check;"
        f" {len(value_failed)} differ on values/rows only; {len(gating_failed)} on names/types;"
        f" {len(unmeasured)} not measured. Sources: "
        + ("identical" if not source_diffs else f"DIFFER ({', '.join(source_diffs)})") + ".")
    log(f"parity: money prediction {'CONFIRMED' if money['prediction_confirmed'] else 'NOT OBSERVED'}"
        f" ({sum(1 for r in money['differing'] if r['differing_rows'])} decimal column(s) with"
        f" differing rows). See parity-report.md.")
    log(f"parity: exit {code} - {reason}")
    return code


# --------------------------------------------------------------------- reports
def write_reports(report):
    with open(REPO / "parity-report.json", "w") as fh:
        json.dump(report, fh, indent=2, default=str)
    (REPO / "parity-report.md").write_text(render_markdown(report))


def _cell(v):
    return f"`{v}`" if v is not None else "n/a"


def render_markdown(report):
    lines = []
    A = lines.append
    v = report.get("verdict") or {}
    models = report["models"]
    A("# Parity report - Spark vs BigQuery")
    A("")
    A(f"Generated {report['generated_at']} by `scripts/parity.py`"
      f" (same-data gating: {'ON (default)' if report['same_data'] else 'off'};"
      f" Spark leg: `{report['spark_source']}`)."
      + (f" Wall time {report['wall_s']} s; BigQuery bytes billed"
         f" {report.get('bigquery_bytes_billed', 0):,}." if "wall_s" in report else ""))
    A("")
    A("## Verdict")
    A("")
    A(f"**Exit {v.get('exit')}: {v.get('reason', '')}**")
    A("")
    if models:
        n_match = sum(1 for e in models if e["verdict"] == "match")
        A(f"* models matching on every check: **{n_match} of {len(models)}**")
        A(f"* differing on names/types (gating): {v.get('gating_failed') or 'none'}")
        A(f"* differing on rows/values only: {len(v.get('value_failed') or [])}"
          + (f" ({', '.join(v['value_failed'])})" if v.get("value_failed") else ""))
        A(f"* not measured: {v.get('unmeasured') or 'none'}")
    A(f"* legs: Spark {report['legs']['spark']}; BigQuery {report['legs']['bigquery']}")
    sc = report.get("self_check") or {}
    A("* digest self-check: " + ("PASS" if sc.get("match") else
                                 ("**FAIL**" if sc else "not run")))
    if report.get("sources"):
        same = [s for s in report["sources"] if s["verdict"] == "match"]
        A(f"* same-data premise: {len(same)} of {len(report['sources'])} sources identical"
          " on every check")
    A("")

    money = report.get("money") or {}
    if money:
        A("## The money prediction (SPEC 6)")
        A("")
        A("Prediction: `money_type()` is `decimal(18,2)` on Spark - exact to its declared")
        A("scale, like the root project's DuckDB - and `NUMERIC` (nine decimals) on")
        A("BigQuery, so the same class of money difference the root project measured")
        A("between DuckDB and BigQuery should appear between Spark and BigQuery.")
        A("")
        diff = [r for r in money["differing"] if r["differing_rows"]]
        if money.get("prediction_confirmed"):
            A(f"**Result: CONFIRMED.** {len(diff)} decimal column(s) differ row by row"
              f" (of {len(money['decimal_columns'])} decimal columns measured;"
              f" {sum(1 for c in money['decimal_columns'] if c['checksum_equal'])} match"
              " exactly). Every differing column, joined on the model's primary key:")
            A("")
            A("| model | column | key | differing rows | rows compared | Spark == BigQuery"
              " rounded to cents | max abs difference | example (key: spark / bigquery) |")
            A("|---|---|---|---|---|---|---|---|")
            for r in money["differing"]:
                ex = r["examples"][0] if r["examples"] else None
                A(f"| `{r['model']}` | `{r['column']}` | `{r['key']}` | {r['differing_rows']:,}"
                  f" | {r['rows_compared']:,} | {r['spark_is_bigquery_rounded_to_cents']:,}"
                  f" | {r['max_abs_difference']} | "
                  + (f"`{ex['key']}`: `{ex['spark']}` / `{ex['bigquery']}`" if ex else "")
                  + " |")
            for k in money.get("keyless", []):
                A(f"| `{k['model']}` | {', '.join(k['columns'])} | (no key) | not computable"
                  f" | | | | {k.get('error', 'checksum differs')} |")
            A("")
            A("Why: the source money columns are FLOAT64. BigQuery casts them to NUMERIC and")
            A("keeps nine decimals (`12.989999771`); Spark casts to `decimal(18,2)` and keeps")
            A("cents (`12.99`). Where the Spark value equals the BigQuery value rounded half-up")
            A("to cents, the difference is exactly that rounding; sums and averages of")
            A("rounded vs unrounded values then drift by more than half a cent.")
        else:
            A("**Result: NOT OBSERVED.** Every decimal column matched exactly"
              f" ({len(money['decimal_columns'])} measured).")
            A("")
            A("Why the reason matters more than the result: the mechanism is still there.")
            A("Spark `decimal(18,2)` rounds to cents on every cast (measured:")
            A("`cast(1.005 as decimal(18,2))` = 1.01) and BigQuery NUMERIC keeps nine")
            A("decimals; the two only agree because no value in today's data carries more")
            A("than two decimals into a money cast. Any upstream value with a third decimal")
            A("(a tax rate, a currency conversion, a FLOAT64 that is not exact in binary)")
            A("would split the engines silently. The checksum would catch it; the types")
            A("would not.")
        A("")
        if money["decimal_columns"]:
            A("<details><summary>Every decimal column and its raw types</summary>")
            A("")
            A("| model | column | Spark raw type | BigQuery raw type | checksum equal |")
            A("|---|---|---|---|---|")
            for c in money["decimal_columns"]:
                A(f"| `{c['model']}` | `{c['column']}` | `{c['spark_type']}` |"
                  f" `{c['bigquery_type']}` | {'yes' if c['checksum_equal'] else '**no**'} |")
            A("")
            A("</details>")
            A("")

    if report.get("sources"):
        A("## The same-data premise: sources")
        A("")
        A("Spark reads the Parquet snapshot `scripts/load_spark_sources.py` pulled;")
        A("BigQuery reads `bigquery-public-data.thelook_ecommerce` live. If these differ,")
        A("model differences are drift, not the engines.")
        A("")
        A("| table | rows spark | rows bigquery | cols | verdict | differences |")
        A("|---|---|---|---|---|---|")
        for s in report["sources"]:
            rc = s.get("row_count") or {}
            A(f"| `{s['table']}` | {rc.get('spark', 'n/a')} | {rc.get('bigquery', 'n/a')} |"
              f" {len(s.get('columns') or [])} | {s['verdict']} |"
              f" {len(s.get('differences') or [])} |")
        A("")
        for s in report["sources"]:
            for d in s.get("differences") or []:
                A(f"* `{s['table']}`" + (f".`{d['column']}`" if d.get("column") else "")
                  + f" {d['check']}: spark {_cell(d['spark'])} vs bigquery {_cell(d['bigquery'])}"
                  + (f" ({d['detail']})" if d.get("detail") else ""))
        geo = [(s["table"], n, t) for s in report["sources"]
               for n, t in (s.get("bigquery_types") or []) if t == "GEOGRAPHY"]
        for t, n, _ in geo:
            A(f"* `{t}.{n}` is GEOGRAPHY on BigQuery and WKT `string` on Spark (the loader"
              " carries it as text); compared as `ST_ASTEXT(x)` vs the string.")
        A("")

    if sc:
        A(f"## Digest self-check: {'PASS' if sc.get('match') else 'FAIL'}")
        A("")
        A("Both engines render a fixture of constants (int, float, bool, date, timestamp,")
        A("string, decimal, array, struct, and an all-NULL row) through the production code")
        A("path - schema discovery, kind mapping, canonical text, md5 digest, SUM - and")
        A("every metric must be identical. The Spark session time zone must be UTC.")
        A("")
        A("| metric | Spark | BigQuery |")
        A("|---|---|---|")
        for k in sorted(sc.get("spark", {})):
            A(f"| {k} | {sc['spark'][k]} | {sc['bigquery'].get(k)} |")
        A("")
        A("| column | Spark kind (raw) | BigQuery kind (raw) |")
        A("|---|---|---|")
        for n, k in sc["kinds"]["spark"].items():
            A(f"| {n} | {k} (`{sc['raw_types']['spark'][n]}`) |"
              f" {sc['kinds']['bigquery'].get(n)} (`{sc['raw_types']['bigquery'].get(n)}`) |")
        A("")
        A(f"Spark session time zone: `{sc.get('spark_session_time_zone')}`.")
        A("")

    if models:
        A("## Per model")
        A("")
        A("| layer | model | rows spark | rows bigquery | cols | verdict | differences"
          " | spark s | bigquery s |")
        A("|---|---|---|---|---|---|---|---|---|")
        order = {"marts": 0, "intermediate": 1, "staging": 2}
        for m in sorted(models, key=lambda m: (order.get(m.get("layer"), 3), m["model"])):
            rc = m.get("row_count") or {}
            secs = m.get("secs") or {}
            A(f"| {m.get('layer', '')} | `{m['model']}` | {rc.get('spark', 'n/a')} |"
              f" {rc.get('bigquery', 'n/a')} | {m.get('columns', '')} | {m['verdict']} |"
              f" {len(m.get('differences') or [])} | {secs.get('spark', 'n/a')} |"
              f" {secs.get('bigquery', 'n/a')} |")
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
            A("| check | column | kind | spark | bigquery | detail |")
            A("|---|---|---|---|---|---|")
            for d in diffs:
                A(f"| {d['check']} | {d.get('column', '')} | {d.get('kind', '')} |"
                  f" {_cell(d['spark'])} | {_cell(d['bigquery'])} | {d.get('detail', '')} |")
            A("")
        if not any_diff:
            A("None: every model matched on every check.")
            A("")

    A("## TRAPS, each with its decision")
    A("")
    A("1. **BIGNUMERIC cannot exist on Spark.** Spark DECIMAL caps at precision 38")
    A("   (measured); `decimal_type(p > 38)` raises on Spark by design instead of")
    A("   rendering `double`. A `bignumeric` canonical type would be named here, never")
    A("   widened away.")
    A("2. **DECIMAL(18,2) vs NUMERIC.** Types compare by *kind* (decimal == numeric),")
    A("   never precision; both raw types are recorded. Values compare exactly after")
    A("   dropping trailing fractional zeros (Spark prints the declared scale, BigQuery")
    A("   the shortest form) - which is where the money prediction is decided.")
    A("3. **Floating point** compares as integer micro-units")
    A("   (`CAST(ROUND(x * 1000000) AS BIGINT/INT64)`), not as text, no tolerance.")
    A("4. **TIMESTAMP vs TIMESTAMP_NTZ**: instants compare as microseconds since the")
    A("   epoch (Spark `unix_micros`, BigQuery `UNIX_MICROS`); `timestamp_ntz`")
    A("   (BigQuery DATETIME) is its own kind, so instant-vs-wall-clock gates. The Spark")
    A("   session must be UTC (checked by the self-check).")
    A("5. **Arrays and structs** compare structurally: arrays sorted and joined with")
    A("   `|`, structs field by field, recursively. A NULL array or struct renders as")
    A("   NULL on both engines, so it is never conflated with an empty one. The Spark")
    A("   adapter cannot fetch an ARRAY column at all; nothing here returns one - only")
    A("   aggregates leave the engine.")
    A("6. **Row order and NULLS ordering**: every metric is an aggregate; the only sort")
    A("   is of an array's own values, the same on both engines.")
    A("7. **NULLs**: explicit null and distinct counts per column, so an all-NULL column")
    A("   cannot masquerade as all-zero.")
    A("8. **The live dataset**: BigQuery reads the public dataset now, Spark a snapshot;")
    A("   the sources are compared first and drift is reported as drift.")
    A("")
    A("## Reproduce")
    A("")
    A("```bash")
    A("make load-sources                          # the Spark snapshot of the real rows")
    A("python3 scripts/parity.py                  # --same-data is the default")
    A("python3 scripts/parity.py --self-check     # only the digest portability step")
    A("```")
    A("")
    A("Both legs are read-only: each model is the ephemeral compile of the DAG, run as")
    A("one query. BigQuery needs `BQ_KEYFILE` (default")
    A("`~/.config/gcp/coreychimpbot-sa.json`) and `openssl`; queries are capped at")
    A("`BQ_MAXIMUM_BYTES_BILLED` (1 GB) each. Spark needs the Thrift Server")
    A("(`scripts/start_spark.sh`) and the loaded sources (`make load-sources`).")
    A("")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
