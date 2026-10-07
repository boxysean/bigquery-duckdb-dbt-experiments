#!/usr/bin/env bash
#
# The whole pre-PR routine of the BigQuery + Spark project in one command, behind
# `make pre-pr`:
#
#   1. scripts/check_env.sh                     prerequisites for both targets
#   2. scripts/check_portability.py             the two-target guardrail
#   3. scripts/parity.py --no-same-data         the structural cross-target comparison
#
# Why: nothing else routinely runs the guardrail. A raw `try_cast(...)` or a
# `{% if target.type == 'spark' %}` branch in a model passes `make spark`, and with a
# target branch both renders are valid SQL, so even parity can pass. Only the
# guardrail catches either.
#
# WHY STEP 3 IS --no-same-data (read this before changing it)
#
#   parity.py has --same-data ON by default. That mode gates on VALUES (row counts,
#   per-column checksums, null and distinct counts) on top of names and types. It is
#   a ~60-minute run that bills ~2.8 GB of BigQuery (measured 2026-10-07: 3599.8 s,
#   2,801,795,072 bytes billed), and it has a known, measured, catalogued result:
#   21 of the 29 models differ on money columns, because Spark's decimal(18,2) is
#   exact to its declared scale while BigQuery NUMERIC keeps nine decimals (54
#   decimal columns differ row by row; see docs/bigquery-to-spark.md and
#   parity-report.md). A pre-PR gate that ran it would be red on every run whatever
#   the code change was, and a gate that is always red is a gate nobody reads.
#
#   So the GATE is the structural comparison: --no-same-data still runs every model
#   on both engines and still runs the digest self-check, but exits 1 only on a
#   column-name or canonical-type mismatch (or a failed self-check); rows and values
#   are reported, not gated. The value measurement is the separate, deliberate,
#   documented `make value-parity` step, run when someone wants the money answer
#   again, not on every PR.
#
#   parity.py always writes parity-report.md/.json in the project root. Those files
#   hold the value-parity result the catalogue quotes, so this script saves them
#   before step 3, moves the gate's own report to target/pre_pr/, and puts the
#   originals back (also on Ctrl-C). The gate never overwrites the value report.
#
# Every step prints a one-line banner (`$ <command>`), the tail of its output, and
# `ok`, `FAIL` or `n/a`, then the next step runs, so one run reports on all of them.
# There is deliberately no `set -e`.
#
# Exit status
#   0  every step ok: prerequisites present, PORTABLE, structural parity established
#   1  a real finding: a missing prerequisite, a portability violation, a structural
#      parity mismatch, a digest self-check failure, or any other non-zero exit
#      (this wins over exit 2 below)
#   2  no finding, but a leg could not be measured: check_portability.py or parity.py
#      exited 2 (no BigQuery credential, no Spark endpoint, the sources not loaded,
#      a compile failure). The step is reported `n/a`, not `FAIL`.
#
# Step 3 needs the Spark Thrift Server (make start-spark), the loaded sources
# (make load-sources) and a BigQuery credential (BQ_KEYFILE, default
# ~/.config/gcp/coreychimpbot-sa.json). It runs real, read-only BigQuery queries,
# each capped by BQ_MAXIMUM_BYTES_BILLED (1 GB), so it costs money and takes about
# 20 minutes. Nothing outside this project is run (no e2e/Playwright, nothing of the
# root project's).
#
# The last line is the total wall time, `pre-pr: <N.N>s`, for recording.
#
set -uo pipefail

project_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$project_root" || exit 1
export DBT_PROFILES_DIR="$project_root"
# The Makefile exports this; set it here too so `bash scripts/pre_pr.sh` run directly
# behaves like `make pre-pr` (measured: dbt-oss 2.0.5 refuses the spark adapter
# without it, and check_env.sh fails on its absence).
export DBT_ALLOW_EXPERIMENTAL_ADAPTERS=true

started_ns=$(date +%s%N)
failures=0
not_measured=0
log=$(mktemp)
saved=$(mktemp -d)
gate_reports="$project_root/target/pre_pr"

# Put the value-parity report back if step 3 moved it aside, however we exit.
restore_reports() {
    local f
    for f in parity-report.md parity-report.json; do
        if [ -f "$saved/$f" ]; then
            mv -f "$saved/$f" "$project_root/$f"
        fi
    done
}
trap 'restore_reports; rm -rf "$log" "$saved"' EXIT
trap 'exit 130' INT TERM

report() { # <status> <command>
    case "$1" in
        ok)  printf '  ok    %s\n' "$2" ;;
        n/a) printf '  n/a   %s\n' "$2"
             not_measured=1 ;;
        *)   printf '  FAIL  %s\n' "$2"
             failures=$((failures + 1)) ;;
    esac
}

# Run a command, show the tail of its output, report its outcome. With
# two_means_unmeasured, an exit 2 is the step's own "could not measure" (n/a);
# otherwise, and for any other non-zero exit, it is a FAIL.
run() { # <two_means_unmeasured: 0|1> <command...>
    local two_is_na=$1
    shift
    printf '\n$ %s\n' "$*"
    "$@" >"$log" 2>&1
    local rc=$?
    tail -n 6 "$log" | sed 's/^/    /'
    if [ "$rc" -eq 0 ]; then
        report ok "$*"
    elif [ "$rc" -eq 2 ] && [ "$two_is_na" -eq 1 ]; then
        report n/a "$* (exit 2: a leg could not be measured, see the output above)"
    else
        report FAIL "$* (exit $rc)"
    fi
}

# Step 3, with the value-parity report saved before and restored after.
parity_step() {
    local f
    for f in parity-report.md parity-report.json; do
        [ -f "$f" ] && cp -p "$f" "$saved/$f"
    done
    run 1 python3 scripts/parity.py --no-same-data
    mkdir -p "$gate_reports"
    for f in parity-report.md parity-report.json; do
        [ -f "$f" ] && mv -f "$f" "$gate_reports/$f"
    done
    restore_reports
    printf '    (the structural report is in %s; the value-parity report is untouched)\n' \
        "${gate_reports#"$project_root"/}"
}

run 0 bash scripts/check_env.sh
run 1 python3 scripts/check_portability.py
parity_step

elapsed_ds=$(( ($(date +%s%N) - started_ns) / 100000000 ))
wall="$((elapsed_ds / 10)).$((elapsed_ds % 10))s"

echo
if [ "$failures" -gt 0 ]; then
    echo "pre-pr: $failures step(s) FAILED"
    echo "pre-pr: $wall"
    exit 1
fi
if [ "$not_measured" -eq 1 ]; then
    echo "NOT ESTABLISHED: a leg could not be measured"
    echo "pre-pr: no step failed, but at least one step could not measure a leg (n/a above):"
    echo "        start the endpoint (make start-spark), load the sources (make load-sources)"
    echo "        and provide a BigQuery credential (BQ_KEYFILE), then run it again."
    echo "pre-pr: $wall"
    exit 2
fi
echo "pre-pr: all steps ok (structural parity; values are make value-parity's job)"
echo "pre-pr: $wall"
exit 0
