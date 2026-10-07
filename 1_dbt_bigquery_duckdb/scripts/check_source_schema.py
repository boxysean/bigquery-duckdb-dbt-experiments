#!/usr/bin/env python3
"""The source-schema check: the fixture's schema IS the real schema IS the declared one.

The local fixture (scripts/fixtures/thelook_ecommerce.sql) stands in for
`bigquery-public-data.thelook_ecommerce` on the DuckDB target. If it lacked a real
column, a model reading that column would build on BigQuery and fail on DuckDB, or
(worse) nothing would read it and the difference would stay silent. This check builds
the fixture into a scratch database and proves, per table:

  * arm A  fixture vs declared: the fixture's columns, in order, equal the columns
           declared in models/staging/_thelook__sources.yml (from the manifest of
           `dbt parse --target duckdb`; offline, no credentials);
  * arm B  declared vs real: the declared columns equal the committed real-schema
           record, scripts/fixtures/real_schema.json (contract drift);
  * arm C  fixture vs real: every fixture column AND its DuckDB type equal the record,
           through one explicit type mapping (REAL_TO_DUCKDB);
  * arm D  every compiled model that reads one of the 7 source relations binds
           against the fixture: DuckDB `EXPLAIN` (its own binder, the binding
           `dbt build` does, no rows read). A missing column is a finding naming the
           model; a model that cannot be bound for another reason (it also reads a
           model) is listed with its error and counted, never skipped silently.

    python3 scripts/check_source_schema.py          # exit 0 ok, 1 findings, 2 could not run
    python3 scripts/check_source_schema.py --demo   # prove the check can fail, then pass
    python3 scripts/check_source_schema.py --emit   # refresh the real-schema record from
                                                    # BigQuery (needs BQ_KEYFILE; tables.get
                                                    # metadata, no query job, bills nothing)

Everything is written under target/schema_check/: the scratch fixture database is
named dev.duckdb (so its catalog is `dev`, which is what compiled SQL references) and
dbt runs with a scratch copy of profiles.yml pointing at it. The developer's
dev.duckdb is neither read nor required.

Stdlib only; runnable from anywhere (it works from the repo root).
"""

import argparse
import datetime
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECT = "bq_duckdb_experiments"
SOURCE = "thelook_ecommerce"
DBT = ROOT / ".venv" / "bin" / "dbt"
DUCKDB_BIN = os.environ.get("DUCKDB_BIN", "duckdb")
CHECK_DIR = Path("target") / "schema_check"
SCRATCH_DB = CHECK_DIR / "dev.duckdb"   # catalog `dev`, as compiled SQL expects
MANIFEST = Path("target") / "manifest.json"
RECORD = Path("scripts") / "fixtures" / "real_schema.json"
SOURCES_YML = "models/staging/_thelook__sources.yml"
DEMO_FILE = Path("models") / "staging" / "_schema_demo.sql"
DEMO_COLUMN = "user_geom_wkt"

# The 7 tables, in the order the source yml declares them.
TABLES = ("orders", "order_items", "users", "products", "inventory_items",
          "distribution_centers", "events")

BQ_PROJECT, BQ_DATASET = "bigquery-public-data", SOURCE
ENDPOINT = ("https://bigquery.googleapis.com/bigquery/v2/projects/{project}"
            "/datasets/{dataset}/tables/{table}")

EXIT_OK, EXIT_FINDINGS, EXIT_CANNOT_RUN = 0, 1, 2

# The one type mapping: real BigQuery type (tables.get spells the legacy names
# INTEGER/FLOAT; the standard-SQL names are accepted too) -> the DuckDB type the
# fixture must have. TIMESTAMP is an absolute instant, hence TIMESTAMPTZ (the source
# contract, D2); GEOGRAPHY is DuckDB's native GEOMETRY (macros/polyglot/types.sql,
# geography_type()). The real loader's DuckDB view of a GEOGRAPHY is GEOMETRY too.
REAL_TO_DUCKDB = {
    "INTEGER": "BIGINT", "INT64": "BIGINT",
    "FLOAT": "DOUBLE", "FLOAT64": "DOUBLE",
    "STRING": "VARCHAR",
    "TIMESTAMP": "TIMESTAMP WITH TIME ZONE",
    "GEOGRAPHY": "GEOMETRY", "GEOMETRY": "GEOMETRY",
}

# DuckDB's binder messages for a column that does not exist.
MISSING_COLUMN = [
    re.compile(r'Referenced column "([^"]+)" not found'),
    re.compile(r'does not have a column named "([^"]+)"'),
]


def tail(text, lines=4):
    return "\n".join("    " + l for l in text.rstrip().splitlines()[-lines:])


def run(cmd, **kw):
    return subprocess.run(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, **kw)


def duck_json(query):
    """Run one query against the scratch database (read-only); the rows as dicts."""
    proc = run([DUCKDB_BIN, "-readonly", "-json", "-init", "/dev/null", str(SCRATCH_DB), "-c", query])
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip())
    out = proc.stdout.strip()
    return json.loads(out) if out else []


# --------------------------------------------------------------------------- setup

def build_fixture():
    """Build the fixture into the scratch dev.duckdb, as scripts/load_duckdb_sources.sh does."""
    (ROOT / CHECK_DIR).mkdir(parents=True, exist_ok=True)
    for p in (SCRATCH_DB, SCRATCH_DB.with_suffix(".duckdb.wal")):
        (ROOT / p).unlink(missing_ok=True)
    cmd = ["bash", "scripts/load_duckdb_sources.sh"]
    print(f"$ DUCKDB_DB={SCRATCH_DB} " + " ".join(cmd))
    proc = run(cmd, env=dict(os.environ, DUCKDB_DB=str(ROOT / SCRATCH_DB), DUCKDB_BIN=DUCKDB_BIN))
    print(tail(proc.stdout + proc.stderr, 1))
    if proc.returncode != 0:
        print(f"the fixture did not build into {SCRATCH_DB} (exit {proc.returncode})")
        return False
    return True


def scratch_profiles():
    """A copy of profiles.yml whose duckdb output points at the scratch database."""
    text = (ROOT / "profiles.yml").read_text(encoding="utf-8")
    pattern = re.compile(r"^(\s*path:\s*)dev\.duckdb\s*$", re.MULTILINE)
    if len(pattern.findall(text)) != 1:
        raise RuntimeError("profiles.yml: expected exactly one `path: dev.duckdb` line")
    text = pattern.sub(lambda m: m.group(1) + str(ROOT / SCRATCH_DB), text)
    (ROOT / CHECK_DIR / "profiles.yml").write_text(text, encoding="utf-8")
    return ROOT / CHECK_DIR


def dbt(args, profiles_dir):
    cmd = [str(DBT.relative_to(ROOT))] + args
    print("$ " + " ".join(cmd))
    proc = run(cmd, env=dict(os.environ, DBT_PROFILES_DIR=str(profiles_dir)))
    out = proc.stdout + proc.stderr
    summary = [l.strip() for l in out.splitlines() if re.match(r"\s*(Finished|Processed|Summary)", l)]
    print("\n".join("    " + l for l in summary) if summary and proc.returncode == 0 else tail(out))
    if proc.returncode != 0:
        print(f"dbt {args[0]} failed (exit {proc.returncode})")
        return False
    return True


# --------------------------------------------------------------------------- the three column lists

def fixture_columns():
    rows = duck_json(
        "select table_name, column_name, data_type from information_schema.columns "
        f"where table_catalog = 'dev' and table_schema = '{SOURCE}' "
        "order by table_name, ordinal_position")
    cols = {}
    for r in rows:
        cols.setdefault(r["table_name"], []).append((r["column_name"], r["data_type"]))
    return cols


def declared_columns(manifest):
    cols = {}
    for key, src in manifest["sources"].items():
        if src.get("source_name") == SOURCE or key.startswith(f"source.{PROJECT}.{SOURCE}."):
            cols[src["name"]] = list(src.get("columns", {}))
    return cols


def load_record():
    rec = json.loads((ROOT / RECORD).read_text(encoding="utf-8"))
    return rec, {t: [(f["name"], f["type"]) for f in fields] for t, fields in rec["tables"].items()}


# --------------------------------------------------------------------------- comparisons

def compare_names(arm, left_label, left, right_label, right):
    """Findings for two per-table ordered name lists."""
    findings = []
    for t in sorted(set(left) | set(right)):
        if t not in right:
            findings.append(f"arm {arm}  {t}: table in the {left_label}, missing from the {right_label}")
            continue
        if t not in left:
            findings.append(f"arm {arm}  {t}: table in the {right_label}, missing from the {left_label}")
            continue
        lnames, rnames = left[t], right[t]
        for c in lnames:
            if c not in rnames:
                findings.append(f"arm {arm}  {t}.{c}: in the {left_label}, missing from the {right_label}")
        for c in rnames:
            if c not in lnames:
                findings.append(f"arm {arm}  {t}.{c}: in the {right_label}, missing from the {left_label}")
        if set(lnames) == set(rnames) and lnames != rnames:
            findings.append(f"arm {arm}  {t}: same columns, different order "
                            f"({left_label}: {', '.join(lnames)}; {right_label}: {', '.join(rnames)})")
    return findings


def compare_types(fixture, real):
    """Arm C: every fixture column and its DuckDB type against the record."""
    findings = compare_names("C", "fixture", {t: [c for c, _ in v] for t, v in fixture.items()},
                             "real record", {t: [c for c, _ in v] for t, v in real.items()})
    for t in sorted(set(fixture) & set(real)):
        have = dict(fixture[t])
        for c, real_type in real[t]:
            if c not in have:
                continue
            want = REAL_TO_DUCKDB.get(real_type.upper())
            if want is None:
                findings.append(f"arm C  {t}.{c}: real type {real_type} has no entry in the "
                                f"type mapping (REAL_TO_DUCKDB); fixture has {have[c]}")
            elif have[c] != want:
                findings.append(f"arm C  {t}.{c}: type differs: real {real_type} -> {want} expected, "
                                f"fixture has {have[c]}")
    return findings


# --------------------------------------------------------------------------- arm D

def relation_regex(relation_name):
    parts = re.findall(r'"([^"]*)"', relation_name) or relation_name.split(".")
    body = r"\s*\.\s*".join(r'"?' + re.escape(p) + r'"?' for p in parts)
    return re.compile(r"(?<![\w.])" + body + r"(?![\w])", re.IGNORECASE)


def bind_models(compile_manifest):
    """EXPLAIN every compiled model that references a source relation.

    Returns (findings, bound model names, [(model, error)] that could not be bound).
    """
    relations = [relation_regex(s["relation_name"]) for k, s in compile_manifest["sources"].items()
                 if s.get("source_name") == SOURCE and s.get("relation_name")]
    base = ROOT / CHECK_DIR / "compiled" / PROJECT / "models"
    findings, bound, unbound = [], [], []
    for path in sorted(base.rglob("*.sql")) if base.is_dir() else []:
        sql = path.read_text(encoding="utf-8")
        if not any(rx.search(sql) for rx in relations):
            continue
        model = path.stem
        proc = run([DUCKDB_BIN, "-readonly", "-bail", "-init", "/dev/null", str(SCRATCH_DB),
                    "-c", "EXPLAIN " + sql.rstrip().rstrip(";") + "\n"])
        if proc.returncode == 0:
            bound.append(model)
            continue
        err = " ".join((proc.stderr or proc.stdout).split())
        missing = next((m.group(1) for rx in MISSING_COLUMN for m in [rx.search(err)] if m), None)
        if "Binder Error" in err and missing:
            findings.append(f"arm D  model {model}: column \"{missing}\" is missing from the fixture "
                            f"({path.relative_to(ROOT).as_posix()}) -> {err[:240]}")
        else:
            unbound.append((model, err[:240]))
    return findings, bound, unbound


# --------------------------------------------------------------------------- the check

def check():
    """Run the four arms; print findings and the summary. Returns (exit code, findings)."""
    if not (ROOT / RECORD).is_file():
        print(f"{RECORD} not found: run `python3 scripts/check_source_schema.py --emit` (needs BQ_KEYFILE)")
        return EXIT_CANNOT_RUN, []
    if not build_fixture():
        return EXIT_CANNOT_RUN, []
    try:
        profiles = scratch_profiles()
    except RuntimeError as e:
        print(e)
        return EXIT_CANNOT_RUN, []
    if not dbt(["parse", "--target", "duckdb"], profiles):
        return EXIT_CANNOT_RUN, []
    manifest = json.loads((ROOT / MANIFEST).read_text(encoding="utf-8"))
    # dbt never deletes the compiled file of a model that no longer exists; start clean.
    shutil.rmtree(ROOT / CHECK_DIR / "compiled", ignore_errors=True)
    if not dbt(["compile", "--target", "duckdb", "--target-path", str(CHECK_DIR)], profiles):
        return EXIT_CANNOT_RUN, []
    compile_manifest = json.loads((ROOT / CHECK_DIR / "manifest.json").read_text(encoding="utf-8"))
    print()

    try:
        fixture = fixture_columns()
    except RuntimeError as e:
        print(f"cannot read the scratch fixture {SCRATCH_DB}: {e}")
        return EXIT_CANNOT_RUN, []
    declared = declared_columns(manifest)
    record, real = load_record()

    fixture_names = {t: [c for c, _ in v] for t, v in fixture.items()}
    real_names = {t: [c for c, _ in v] for t, v in real.items()}
    arm_a = compare_names("A", "fixture", fixture_names, f"declared sources ({SOURCES_YML})", declared)
    arm_b = compare_names("B", f"declared sources ({SOURCES_YML})", declared, f"real record ({RECORD})", real_names)
    arm_c = compare_types(fixture, real)
    arm_d, bound, unbound = bind_models(compile_manifest)

    findings = arm_a + arm_b + arm_c + arm_d
    for line in findings:
        print(line)
    if findings:
        print()
    if unbound:
        print(f"models that read a source but could not be bound against the fixture alone "
              f"(not findings; listed so none is skipped silently): {len(unbound)}")
        for model, err in unbound:
            print(f"  {model}: {err}")
        print()

    n_fixture = sum(len(v) for v in fixture.values())
    n_declared = sum(len(v) for v in declared.values())
    n_real = sum(len(v) for v in real.values())
    print(f"real-schema record: {RECORD} ({record.get('source')}, captured {record.get('captured_at_utc')}, "
          f"by {record.get('captured_by')})")
    print(f"tables: fixture {len(fixture)}, declared {len(declared)}, real {len(real)}; "
          f"columns: fixture {n_fixture}, declared {n_declared}, real {n_real}")
    print(f"arm A  fixture vs declared:         {len(arm_a)} finding(s)")
    print(f"arm B  declared vs real:            {len(arm_b)} finding(s)")
    print(f"arm C  fixture vs real (+ types):   {len(arm_c)} finding(s)")
    print(f"arm D  source-reading models bound: {len(bound)} bound, {len(arm_d)} finding(s), "
          f"{len(unbound)} could not be bound for another reason")
    if findings:
        print(f"FIXTURE SCHEMA: {len(findings)} finding(s)")
        return EXIT_FINDINGS, findings
    print("FIXTURE SCHEMA OK")
    return EXIT_OK, findings


# --------------------------------------------------------------------------- --emit

def emit():
    """Refresh the real-schema record from BigQuery tables.get metadata (no query job)."""
    key = os.environ.get("BQ_KEYFILE")
    if not key or not Path(key).is_file():
        print("--emit: BQ_KEYFILE is not set or is not a file")
        return EXIT_CANNOT_RUN
    # One implementation of the JWT exchange in this repository: parity.py's.
    spec = importlib.util.spec_from_file_location("parity", ROOT / "scripts" / "parity.py")
    parity = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parity)
    try:
        token = parity.access_token(key)
    except Exception as e:  # noqa: BLE001
        print(f"--emit: could not obtain an access token: {e}")
        return EXIT_CANNOT_RUN
    captured = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tables = {}
    for table in TABLES:
        url = ENDPOINT.format(project=BQ_PROJECT, dataset=BQ_DATASET, table=table)
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                meta = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            print(f"--emit: {BQ_PROJECT}.{BQ_DATASET}.{table}: HTTP {e.code}: {e.read().decode()[:400]}")
            return EXIT_CANNOT_RUN
        fields = meta.get("schema", {}).get("fields", [])
        tables[table] = [{"name": f["name"], "type": f["type"], "mode": f.get("mode", "NULLABLE")}
                         for f in fields]
        print(f"  {table:<22} {len(fields):3d} columns")
    record = {
        "source": f"{BQ_PROJECT}.{BQ_DATASET}",
        "endpoint": "GET " + ENDPOINT.format(project=BQ_PROJECT, dataset=BQ_DATASET, table="{table}"),
        "field": "schema.fields",
        "captured_at_utc": captured,
        "captured_by": "python3 scripts/check_source_schema.py --emit",
        "note": ("Public schema metadata only (tables.get: read-only, not a query job, bills "
                 "nothing). Column order is the table's. Read by scripts/check_source_schema.py."),
        "tables": tables,
    }
    (ROOT / RECORD).write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"--emit: wrote {RECORD} ({len(tables)} tables, "
          f"{sum(len(v) for v in tables.values())} columns, captured {captured})")
    return EXIT_OK


# --------------------------------------------------------------------------- --demo

DEMO_SQL = f"""\
-- Written by `scripts/check_source_schema.py --demo` and deleted again by it.
-- `{DEMO_COLUMN}` is a column the fixture does not define.
select id, {DEMO_COLUMN} from {{{{ source('thelook_ecommerce', 'users') }}}}
"""


def demo():
    """Make the check fail on purpose, then pass again."""
    demo_path = ROOT / DEMO_FILE
    if demo_path.exists():
        print(f"{DEMO_FILE} already exists; remove it before running --demo")
        return EXIT_CANNOT_RUN

    failed_as_designed = False
    try:
        demo_path.write_text(DEMO_SQL, encoding="utf-8")
        print(f"demo: wrote {DEMO_FILE} (selects {DEMO_COLUMN} from the users source)\n")
        code, findings = check()
        name = DEMO_FILE.stem
        hits = [f for f in findings if f"model {name}:" in f and f'"{DEMO_COLUMN}"' in f]
        failed_as_designed = code == EXIT_FINDINGS and bool(hits)
        print()
        if failed_as_designed:
            print(f"demo: the check failed as designed ({len(hits)} finding(s) naming "
                  f"{DEMO_COLUMN} in {name})")
        else:
            print(f"demo: FAIL - expected a finding naming {DEMO_COLUMN} in {name} "
                  f"(got exit {code}, {len(hits)} such finding(s))")
    finally:
        demo_path.unlink(missing_ok=True)
        # The compiled tree now holds the demo model; drop it so no stale render survives.
        shutil.rmtree(ROOT / CHECK_DIR / "compiled", ignore_errors=True)
        print(f"demo: removed {DEMO_FILE}\n")

    if not failed_as_designed:
        return EXIT_FINDINGS

    code, _ = check()
    print()
    if code != EXIT_OK:
        print(f"demo: FAIL - the re-check after removing {DEMO_FILE} did not pass (exit {code})")
        return EXIT_FINDINGS if code == EXIT_FINDINGS else code
    print("demo: the check failed as designed, then passed again")
    return EXIT_OK


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--demo", action="store_true",
                      help="inject a model reading a column the fixture lacks, show the check fail, "
                           "remove it, show it pass")
    mode.add_argument("--emit", action="store_true",
                      help=f"refresh {RECORD} from BigQuery tables.get metadata (needs BQ_KEYFILE)")
    args = parser.parse_args()

    os.chdir(ROOT)
    # SIGTERM should unwind like Ctrl-C so the demo's `finally` still deletes its file.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(EXIT_CANNOT_RUN))

    if args.emit:
        return emit()
    if not DBT.exists():
        print(f"{DBT.relative_to(ROOT)} not found: run make setup first")
        return EXIT_CANNOT_RUN
    if shutil.which(DUCKDB_BIN) is None:
        print(f"DuckDB CLI not found ({DUCKDB_BIN}): run make setup or set DUCKDB_BIN")
        return EXIT_CANNOT_RUN
    if args.demo:
        return demo()
    return check()[0]


if __name__ == "__main__":
    sys.exit(main())
