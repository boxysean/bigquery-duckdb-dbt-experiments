#!/usr/bin/env python3
"""The two-target portability guardrail (SPEC section 4).

Compiles the project for BOTH targets into separate trees, then proves with
counts that neither render carries the other engine's dialect, and that no model
or test branches on the target:

  * the Spark render must carry no BigQuery-only token;
  * the BigQuery render must carry no Spark-only token;
  * nothing under models/ or tests/ may mention target.type / target.name /
    target.database / target.schema / adapter.type (one allowlisted file).

    python3 scripts/check_portability.py          # exit 0 portable, 1 findings, 2 could not run
    python3 scripts/check_portability.py --demo   # prove the guardrail can fail, then pass

Stdlib only; runnable from anywhere (it works from the project root,
bigquery_spark/). Compiling the spark target needs the local Thrift Server
(scripts/start_spark.sh); nothing is built or run.
"""

import argparse
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECT = "bq_spark_experiments"
DBT = ROOT.parent.parent / "1_dbt_bigquery_duckdb" / ".venv" / "bin" / "dbt"
PORTABILITY_DIR = Path("target") / "portability"
TARGETS = ("bigquery", "spark")
SCANNED_DIRS = ("models", "analyses")
DEMO_FILE = Path("models") / "intermediate" / "_portability_demo.sql"
SPARK_ENDPOINT = ("127.0.0.1", 10000)

EXIT_PORTABLE, EXIT_FINDINGS, EXIT_CANNOT_RUN = 0, 1, 2

# --- the two directional token lists (SPEC 4) -----------------------------------
# Every token was measured on this box on 2026-10-06 before it went in a list:
#   * BIGQUERY_ONLY: each one executed against the real Spark 4.2.0 Thrift Server
#     (beeline, jdbc:hive2://127.0.0.1:10000) and was REJECTED: float64/bignumeric/
#     array<int64> -> UNSUPPORTED_DATATYPE; safe_cast -> PARSE_SYNTAX_ERROR;
#     safe_divide, generate_array, generate_date_array, regexp_contains, format_date,
#     timestamp_trunc, timestamp_diff -> UNRESOLVED_ROUTINE; `bigquery-public-data`
#     -> REQUIRES_SINGLE_PART_NAMESPACE; date_diff(a, b, day) -> UNRESOLVED_COLUMN.
#     Caveat on `date_diff(`: Spark 4.2 DOES have its own date_diff(end, start) and
#     date_diff(unit, start, end) (both measured: 4). The token is still the right
#     ban: the Spark branch of the seam spells it datediff(), so a date_diff( in the
#     Spark render is the BigQuery spelling leaking through.
#   * SPARK_ONLY: each one dry-run against real BigQuery (free, 0 bytes) and REJECTED
#     ("Function not found", "Type not found", "Syntax error", "Invalid project ID").
#     Two SPEC seed tokens were ACCEPTED by BigQuery and are therefore NOT in the list:
#     `unix_micros(` (BigQuery has UNIX_MICROS) and `array<bigint>` (BIGINT is a
#     BigQuery alias of INT64). Banning them would flag valid BigQuery.
# `* except (` is deliberately in NEITHER list: measured to work on both engines
# (Spark 4.2 accepts the BigQuery spelling; BigQuery dry run accepted). The same
# goes for `struct(` (identical on both, SPEC 0).
BIGQUERY_ONLY = [  # must not appear in the Spark render
    "float64", "safe_cast", "safe_divide", "generate_array", "generate_date_array",
    "regexp_contains", "format_date(", "timestamp_trunc", "timestamp_diff", "bignumeric",
    "array<int64>", "bigquery-public-data", "date_diff(",
]
SPARK_ONLY = [  # must not appear in the BigQuery render
    "try_cast", "try_divide", "sequence(", "explode(", "lateral view", "date_format(",
    "datediff(", "dayofweek(", "regexp_like(", "timestamp_ntz", "spark_catalog",
    "default.thelook_ecommerce",
]

# --- the purity check (SPEC 4) ---------------------------------------------------
PURITY_TOKENS = ["target.type", "target.name", "target.database", "target.schema", "adapter.type"]
PURITY_DIRS = ("models", "tests")
PURITY_ALLOWLIST = {
    # The source *database* name is the single thing that is genuinely
    # target-dependent: `bigquery-public-data` on BigQuery, the local Spark
    # catalog on Spark. It is declared in one line of the source definition and
    # cannot live in a model, so this file is the one place allowed to read the target.
    "models/staging/_thelook__sources.yml",
}


def token_regex(token):
    """Case-insensitive regex for one token.

    Whitespace inside a token, and before a `(`, `<` or `[`, is matched as `\\s*` so
    that `lateral  view` or `array <int64>` cannot slip past on spacing alone. A token
    that starts (ends) with a letter or digit must start (end) an identifier: the
    showcase analysis aliases a column `safe_cast_number`, which is a name, not a
    call to BigQuery's SAFE_CAST, and must not be reported. Every genuine use of a
    word token (`safe_cast(`, `as float64`, ...) is still delimited, so none is lost.
    `date_diff(` (BigQuery-direction) matches only when not followed by a quote:
    `date_diff('day', ...)` is a string-unit spelling, `date_diff(a, b, day)` BigQuery's.
    """
    if token == "date_diff(":
        body = r"date_diff\s*\((?!\s*['\"])"
    else:
        body = ""
        for ch in token:
            if ch == " ":
                body += r"\s*"
            elif ch == ".":
                # dbt quotes relation parts (backticks on both engines), so a bare
                # `default.thelook_ecommerce` would never match a real leak.
                body += r"[\"`]?\.[\"`]?"
            elif ch in "(<[":
                body += r"\s*" + re.escape(ch) + r"\s*"
            else:
                body += re.escape(ch)
    if token[0].isalnum():
        body = r"(?<!\w)" + body
    if token[-1].isalnum():
        body += r"(?!\w)"
    return re.compile(body, re.IGNORECASE)


def strip_sql_comments(text):
    """Blank out `-- ...` and `/* ... */` comments, keeping line numbers intact.

    Quoted strings ('...', "...", `...`) are left alone, so a `--` inside a string
    literal is not mistaken for a comment.
    """
    out = []
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in "'\"`":
            j = i + 1
            while j < n:
                if text[j] == ch:
                    if j + 1 < n and text[j + 1] == ch:  # doubled quote escape
                        j += 2
                        continue
                    break
                if text[j] == "\\":
                    j += 1
                j += 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("--", i):
            j = text.find("\n", i)
            j = n if j == -1 else j
            out.append(" " * (j - i))
            i = j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j == -1 else j + 2
            out.append(re.sub(r"[^\n]", " ", text[i:j]))
            i = j
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def tail(text, lines=4):
    return "\n".join("    " + l for l in text.rstrip().splitlines()[-lines:])


def compile_target(target):
    """`dbt compile` one target into its own fresh tree. Returns True on success.

    The tree is removed first: dbt never deletes the compiled file of a model that
    no longer exists, and a stale file would be scanned as if it were current.
    """
    target_path = PORTABILITY_DIR / target
    shutil.rmtree(ROOT / target_path, ignore_errors=True)
    cmd = [os.path.relpath(DBT, ROOT), "compile", "--target", target, "--target-path", str(target_path)]
    print("$ " + " ".join(cmd))
    # The spark adapter is experimental in dbt-oss 2.0.5 and refused without the flag.
    env = dict(os.environ, DBT_PROFILES_DIR=str(ROOT), DBT_ALLOW_EXPERIMENTAL_ADAPTERS="true")
    proc = subprocess.run(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True)
    print(tail(proc.stdout))
    if proc.returncode != 0:
        print(f"dbt compile --target {target} failed (exit {proc.returncode})")
        return False
    return True


def compiled_files(target):
    """Compiled .sql files to scan, per SCANNED_DIRS entry."""
    base = ROOT / PORTABILITY_DIR / target / "compiled" / PROJECT
    return {sub: sorted((base / sub).rglob("*.sql")) if (base / sub).is_dir() else []
            for sub in SCANNED_DIRS}


def scan_render(target, tokens):
    """Scan one compiled tree. Returns (findings, distinct tokens hit, per-dir file counts)."""
    regexes = [(t, token_regex(t)) for t in tokens]
    findings, hit = [], set()
    files = compiled_files(target)
    for path in (p for sub in SCANNED_DIRS for p in files[sub]):
        raw = path.read_text(encoding="utf-8").splitlines()
        stripped = strip_sql_comments("\n".join(raw)).splitlines()
        for lineno, line in enumerate(stripped, 1):
            for token, rx in regexes:
                if rx.search(line):
                    hit.add(token)
                    findings.append(f"{path.relative_to(ROOT).as_posix()}:{lineno}: "
                                    f"token '{token}' -> {raw[lineno - 1].strip()}")
    return findings, hit, {sub: len(files[sub]) for sub in SCANNED_DIRS}


def scan_purity():
    findings = []
    for top in PURITY_DIRS:
        if not (ROOT / top).is_dir():
            continue
        for path in sorted((ROOT / top).rglob("*")):
            rel = path.relative_to(ROOT).as_posix()
            if not path.is_file() or rel in PURITY_ALLOWLIST:
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            for lineno, line in enumerate(lines, 1):
                for token in PURITY_TOKENS:
                    if token in line.lower():
                        findings.append(f"{rel}:{lineno}: token '{token}' -> {line.strip()}")
    return findings


def check(targets=TARGETS):
    """Compile `targets`, scan, print findings and the summary.

    Returns (exit code, the printed finding lines).
    """
    for target in targets:
        if not compile_target(target):
            return EXIT_CANNOT_RUN, []
    print()

    none = ([], set(), None)
    spark_findings, spark_hit, counts = scan_render("spark", BIGQUERY_ONLY) if "spark" in targets else none
    bq_findings, bq_hit, bq_counts = scan_render("bigquery", SPARK_ONLY) if "bigquery" in targets else none
    purity_findings = scan_purity()
    counts = counts or bq_counts

    findings = spark_findings + bq_findings + purity_findings
    for line in findings:
        print(line)
    if findings:
        print()

    n_files = sum(counts.values())
    print(f"compiled files checked: {n_files} (models: {counts['models']}, analyses: {counts['analyses']})")
    skipped = "not compiled in this run"
    print(f"BigQuery-only tokens in the Spark render: "
          + (f"{len(spark_hit)}/{len(BIGQUERY_ONLY)}" if "spark" in targets else skipped))
    print(f"Spark-only tokens in the BigQuery render: "
          + (f"{len(bq_hit)}/{len(SPARK_ONLY)}" if "bigquery" in targets else skipped))
    print(f"target-branch findings: {len(purity_findings)}")
    if findings:
        print(f"NOT PORTABLE: {len(findings)} finding(s)")
        return EXIT_FINDINGS, findings
    print("PORTABLE")
    return EXIT_PORTABLE, findings


DEMO_SQL = """\
-- Written by `scripts/check_portability.py --demo` and deleted again by it.
-- Both lines below are deliberate portability leaks.
select regexp_contains('a', 'a') as demo from {{ ref('stg_thelook__users') }}
{% if target.type == 'bigquery' %}limit 1{% endif %}
"""


def demo():
    """SPEC 4: make the guardrail fail on purpose, then pass again."""
    demo_path = ROOT / DEMO_FILE
    if demo_path.exists():
        print(f"{DEMO_FILE} already exists; remove it before running --demo")
        return EXIT_CANNOT_RUN

    failed_as_designed = False
    try:
        demo_path.write_text(DEMO_SQL, encoding="utf-8")
        print(f"demo: wrote {DEMO_FILE} (raw regexp_contains + a target.type branch)\n")
        code, findings = check(targets=("spark",))
        name = DEMO_FILE.name
        token_hits = [f for f in findings if name in f and "token 'regexp_contains'" in f]
        branch_hits = [f for f in findings if name in f and "token 'target.type'" in f]
        failed_as_designed = code == EXIT_FINDINGS and bool(token_hits) and bool(branch_hits)
        print()
        if failed_as_designed:
            print(f"demo: guardrail failed as designed ({len(token_hits)} dialect finding(s), "
                  f"{len(branch_hits)} target-branch finding(s) in {name})")
        else:
            print(f"demo: FAIL - expected >=1 dialect and >=1 target-branch finding in {name} "
                  f"(got exit {code}, {len(token_hits)} dialect, {len(branch_hits)} target-branch)")
    finally:
        demo_path.unlink(missing_ok=True)
        # The Spark tree now holds the demo model's compiled file; drop it so no
        # stale render survives even if the re-check below never runs.
        shutil.rmtree(ROOT / PORTABILITY_DIR / "spark", ignore_errors=True)
        print(f"demo: removed {DEMO_FILE}\n")

    if not failed_as_designed:
        return EXIT_FINDINGS

    code, _ = check()
    print()
    if code != EXIT_PORTABLE:
        print(f"demo: FAIL - the re-check after removing {DEMO_FILE} did not pass (exit {code})")
        return EXIT_FINDINGS if code == EXIT_FINDINGS else code
    print("demo: the guardrail failed as designed, then passed again")
    return EXIT_PORTABLE


def spark_endpoint_up():
    try:
        with socket.create_connection(SPARK_ENDPOINT, timeout=3):
            return True
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo", action="store_true",
                        help="inject a temporary leaking model, show the guardrail fail, remove it, show it pass")
    args = parser.parse_args()

    os.chdir(ROOT)
    # SIGTERM should unwind like Ctrl-C so the demo's `finally` still deletes its file.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(EXIT_CANNOT_RUN))

    if not DBT.exists():
        print(f"{os.path.relpath(DBT, ROOT)} not found: run `uv sync` in the repository root first")
        return EXIT_CANNOT_RUN
    if not spark_endpoint_up():
        host, port = SPARK_ENDPOINT
        print(f"no Spark Thrift Server on {host}:{port}: run make start-spark first")
        return EXIT_CANNOT_RUN

    if args.demo:
        return demo()
    return check()[0]


if __name__ == "__main__":
    sys.exit(main())
