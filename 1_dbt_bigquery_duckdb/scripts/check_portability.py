#!/usr/bin/env python3
"""The portability guardrail (SPEC section 7.4).

Compiles the project for BOTH targets into separate trees, then proves with
counts that neither render carries the other engine's dialect, and that no model
or test branches on the target:

  * the DuckDB render must carry no BigQuery-only token;
  * the BigQuery render must carry no DuckDB-only token;
  * nothing under models/ or tests/ may mention target.type / target.name /
    target.database / target.schema / adapter.type (one allowlisted file).

    python3 scripts/check_portability.py          # exit 0 portable, 1 findings, 2 could not run
    python3 scripts/check_portability.py --demo   # prove the guardrail can fail, then pass

Stdlib only; runnable from anywhere (it works from the repo root).
"""

import argparse
import os
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECT = "bq_duckdb_experiments"
DBT = ROOT / ".venv" / "bin" / "dbt"
PORTABILITY_DIR = Path("target") / "portability"
TARGETS = ("duckdb", "bigquery")
SCANNED_DIRS = ("models", "analyses")
# The transport measurement scenarios are committed evidence for `make transport-a` /
# `make transport-b`, run by their own harnesses, not the warehouse project. dbt still
# compiles every .sql under analyses/ as an analysis, and those scenarios are deliberately
# engine-specific, so they are dropped from the scan (the same reason
# scripts/move_to_duckdb.py skips them). The list is explicit on purpose: a new
# analyses/transport_c/ is NOT excluded, it shows up as findings until someone decides here.
EXCLUDED_ANALYSES = ("analyses/transport_a", "analyses/transport_b")
DEMO_FILE = Path("models") / "intermediate" / "_portability_demo.sql"

EXIT_PORTABLE, EXIT_FINDINGS, EXIT_CANNOT_RUN = 0, 1, 2

# --- the two directional token lists, verbatim from SPEC 7.4 ------------------
# Every token was measured against DuckDB 1.5.5. `int64` is *accepted* by DuckDB,
# so it is deliberately not a DuckDB-direction token; `float64` is rejected, so it is.
BIGQUERY_ONLY = [  # must not appear in the DuckDB render
    "float64", "safe_cast", "safe_divide", "generate_array", "generate_date_array",
    "regexp_contains", "format_date", "timestamp_trunc", "timestamp_diff", "bignumeric",
    "struct(", "* except (", "array<", "date_diff(", "bigquery-public-data",
]
DUCKDB_ONLY = [  # must not appear in the BigQuery render
    "try_cast", "regexp_matches", "strftime", "generate_series", "list_value",
    "struct_pack", "epoch_ms", "* exclude (", "bigint[]", "::", "date_trunc('",
    "date_diff('", "dev.thelook_ecommerce",
]

# --- positive type coverage (card t_68bfec9c) ----------------------------------
# The token lists above only prove ABSENCE. The array/struct/JSON renderings must
# also be PRESENT in each render of the one model that carries them, or a macro that
# silently dropped its construct would pass as "portable".
TYPE_SHOWCASE_MODEL = "mart_polyglot_types"
TYPE_COVERAGE = {
    "duckdb": ["generate_series(", "date[]", "'id':", "'channel':", "to_json("],
    "bigquery": ["generate_array(", "generate_date_array(", "struct(", "to_json("],
}

# --- the purity check (SPEC 7.4 item 3) ----------------------------------------
PURITY_TOKENS = ["target.type", "target.name", "target.database", "target.schema", "adapter.type"]
PURITY_DIRS = ("models", "tests")
PURITY_ALLOWLIST = {
    # The source *database* name is the single thing that is genuinely
    # target-dependent: `bigquery-public-data` on BigQuery, the local fixture
    # catalog on DuckDB. It is declared in one line of the source definition and
    # cannot live in a model, so this file is the one place allowed to read the target.
    "models/staging/_thelook__sources.yml",
}


def token_regex(token):
    """Case-insensitive regex for one token.

    Whitespace inside a token, and before a `(`, `<` or `[`, is matched as `\\s*` so
    that `* except(` or `array <` cannot slip past on spacing alone. A token that
    starts (ends) with a letter or digit must start (end) an identifier: the
    showcase analysis aliases a column `safe_cast_number`, which is a name, not a
    call to BigQuery's SAFE_CAST, and must not be reported. Every genuine use of a
    word token (`safe_cast(`, `as float64`, ...) is still delimited, so none is lost.
    `date_diff(` (BigQuery-direction) matches only when not followed by a quote:
    `date_diff('day', ...)` is the DuckDB spelling, `date_diff(a, b, day)` BigQuery's.
    """
    if token == "date_diff(":
        body = r"date_diff\s*\((?!\s*['\"])"
    else:
        body = ""
        for ch in token:
            if ch == " ":
                body += r"\s*"
            elif ch == ".":
                # dbt quotes relation parts (`"dev"."thelook_ecommerce"`, backticks on
                # BigQuery), so a bare `dev.thelook_ecommerce` would never match a real leak.
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
    cmd = [str(DBT.relative_to(ROOT)), "compile", "--target", target, "--target-path", str(target_path)]
    print("$ " + " ".join(cmd))
    env = dict(os.environ, DBT_PROFILES_DIR=str(ROOT))
    proc = subprocess.run(cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True)
    print(tail(proc.stdout))
    if proc.returncode != 0:
        print(f"dbt compile --target {target} failed (exit {proc.returncode})")
        return False
    return True


def excluded_prefix(rel):
    """The EXCLUDED_ANALYSES prefix covering a compiled-tree posix path, else None."""
    for prefix in EXCLUDED_ANALYSES:
        if rel == prefix or rel.startswith(prefix + "/"):
            return prefix
    return None


def compiled_files(target):
    """Compiled .sql files to scan per SCANNED_DIRS entry, and files dropped per excluded prefix."""
    base = ROOT / PORTABILITY_DIR / target / "compiled" / PROJECT
    files, dropped = {}, dict.fromkeys(EXCLUDED_ANALYSES, 0)
    for sub in SCANNED_DIRS:
        files[sub] = []
        for path in sorted((base / sub).rglob("*.sql")) if (base / sub).is_dir() else []:
            prefix = excluded_prefix(path.relative_to(base).as_posix())
            if prefix:
                dropped[prefix] += 1
            else:
                files[sub].append(path)
    return files, dropped


def scan_render(target, tokens):
    """Scan one compiled tree.

    Returns (findings, distinct tokens hit, per-dir file counts, per-prefix excluded counts).
    """
    regexes = [(t, token_regex(t)) for t in tokens]
    findings, hit = [], set()
    files, dropped = compiled_files(target)
    for path in (p for sub in SCANNED_DIRS for p in files[sub]):
        raw = path.read_text(encoding="utf-8").splitlines()
        stripped = strip_sql_comments("\n".join(raw)).splitlines()
        for lineno, line in enumerate(stripped, 1):
            for token, rx in regexes:
                if rx.search(line):
                    hit.add(token)
                    findings.append(f"{path.relative_to(ROOT).as_posix()}:{lineno}: "
                                    f"token '{token}' -> {raw[lineno - 1].strip()}")
    return findings, hit, {sub: len(files[sub]) for sub in SCANNED_DIRS}, dropped


def scan_type_coverage(targets=TARGETS):
    """Every TYPE_COVERAGE substring must be in the compiled TYPE_SHOWCASE_MODEL, per target."""
    findings = []
    for target in targets:
        path = (ROOT / PORTABILITY_DIR / target / "compiled" / PROJECT / "models" / "marts"
                / f"{TYPE_SHOWCASE_MODEL}.sql")
        rel = path.relative_to(ROOT).as_posix()
        if not path.is_file():
            findings.append(f"{rel}: missing - the {target} render has no {TYPE_SHOWCASE_MODEL}, "
                            f"so the array/struct/json rendering is not exercised on {target}")
            continue
        text = strip_sql_comments(path.read_text(encoding="utf-8")).lower()
        for needle in TYPE_COVERAGE[target]:
            if needle.lower() not in text:
                findings.append(f"{rel}: required '{needle}' missing - the {target} render of "
                                f"{TYPE_SHOWCASE_MODEL} dropped an array/struct/json construct")
    return findings


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

    none = ([], set(), None, None)
    duck_findings, duck_hit, counts, dropped = scan_render("duckdb", BIGQUERY_ONLY) if "duckdb" in targets else none
    bq_findings, bq_hit, bq_counts, bq_dropped = scan_render("bigquery", DUCKDB_ONLY) if "bigquery" in targets else none
    purity_findings = scan_purity()
    coverage_findings = scan_type_coverage(targets)
    counts = counts or bq_counts
    dropped = dropped if "duckdb" in targets else bq_dropped

    findings = duck_findings + bq_findings + purity_findings + coverage_findings
    for line in findings:
        print(line)
    if findings:
        print()

    print("excluded from the scan (measurement scenarios, not the warehouse project):")
    for prefix in sorted(dropped):
        print(f"  {prefix}  {dropped[prefix]} file(s)")
    n_files = sum(counts.values())
    print(f"compiled files checked: {n_files} (models: {counts['models']}, analyses: {counts['analyses']})")
    skipped = "not compiled in this run"
    print(f"BigQuery-only tokens in the DuckDB render: "
          + (f"{len(duck_hit)}/{len(BIGQUERY_ONLY)}" if "duckdb" in targets else skipped))
    print(f"DuckDB-only tokens in the BigQuery render: "
          + (f"{len(bq_hit)}/{len(DUCKDB_ONLY)}" if "bigquery" in targets else skipped))
    print(f"target-branch findings: {len(purity_findings)}")
    covered = "both renders" if len(targets) == len(TARGETS) else f"the {targets[0]} render"
    print(f"type coverage ({TYPE_SHOWCASE_MODEL}): "
          + (f"{len(coverage_findings)} finding(s)" if coverage_findings
             else f"array/struct/json present in {covered}"))
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
    """SPEC 7.4 item 5: make the guardrail fail on purpose, then pass again."""
    demo_path = ROOT / DEMO_FILE
    if demo_path.exists():
        print(f"{DEMO_FILE} already exists; remove it before running --demo")
        return EXIT_CANNOT_RUN

    failed_as_designed = False
    try:
        demo_path.write_text(DEMO_SQL, encoding="utf-8")
        print(f"demo: wrote {DEMO_FILE} (raw regexp_contains + a target.type branch)\n")
        code, findings = check(targets=("duckdb",))
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
        # The DuckDB tree now holds the demo model's compiled file; drop it so no
        # stale render survives even if the re-check below never runs.
        shutil.rmtree(ROOT / PORTABILITY_DIR / "duckdb", ignore_errors=True)
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


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo", action="store_true",
                        help="inject a temporary leaking model, show the guardrail fail, remove it, show it pass")
    args = parser.parse_args()

    os.chdir(ROOT)
    # SIGTERM should unwind like Ctrl-C so the demo's `finally` still deletes its file.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(EXIT_CANNOT_RUN))

    if not DBT.exists():
        print(f"{DBT.relative_to(ROOT)} not found: run make setup first")
        return EXIT_CANNOT_RUN
    if not (ROOT / "dev.duckdb").exists():
        print("dev.duckdb not found: run make fixtures first")
        return EXIT_CANNOT_RUN

    if args.demo:
        return demo()
    return check()[0]


if __name__ == "__main__":
    sys.exit(main())
