#!/usr/bin/env bash
#
# The whole pre-PR routine in one command, behind `make pre-pr`:
#
#   1. scripts/check_env.sh                     prerequisites
#   2. scripts/load_duckdb_sources.sh           the DuckDB fixture (dev.duckdb)
#   3. scripts/check_portability.py             the guardrail
#   4. scripts/parity.py                        the cross-target comparison
#
# Why: nothing else routinely runs the guardrail. A raw `try_cast(...)` or a
# `{% if target.type == 'duckdb' %}` branch in a model passes `make duck`, and
# without credentials `make parity` then exits 2 ("NOT established"), which reads
# like "skipped, fine"; with credentials a target branch even passes parity,
# because both branches are valid SQL. Only the guardrail catches either.
#
# Step 2 is not optional: check_portability.py refuses to run without dev.duckdb
# (exit 2, "run make fixtures first"). It takes about half a second. `make duck` is
# deliberately not called: parity.py already runs it (fixtures + dbt build --target
# duckdb) plus a DuckDB baseline rebuild, and a second build would only cost time.
#
# Every step prints `ok` or `FAIL` with the command it ran and keeps going, so one
# run reports on all of them. There is deliberately no `set -e`.
#
# Exit status
#   0  every step ok, parity established on both targets
#   1  a real finding: any step failed (this wins over exit 2 below)
#   2  every other step ok, but parity.py exited 2: the BigQuery leg could not be
#      measured (no BQ_KEYFILE), so parity is NOT established. Not a portability
#      finding; the step is reported `n/a`, not `FAIL`.
#
# With BQ_KEYFILE set, the parity step runs real BigQuery queries, read-only and
# capped at 1 GB billed (maximum_bytes_billed), so it costs money.
#
# The last line is the total wall time, `pre-pr: <N.N>s`, for recording.
#
set -uo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root" || exit 1
export DBT_PROFILES_DIR="$repo_root"

started_ns=$(date +%s%N)
failures=0
parity_not_established=0
log=$(mktemp)
trap 'rm -f "$log"' EXIT

report() { # <status> <command>
    case "$1" in
        ok)  printf '  ok    %s\n' "$2" ;;
        n/a) printf '  n/a   %s\n' "$2" ;;
        *)   printf '  FAIL  %s\n' "$2"
             failures=$((failures + 1)) ;;
    esac
}

# Run a command, show the tail of its output, report ok iff it exits 0.
step() { # <command...>
    printf '\n$ %s\n' "$*"
    "$@" >"$log" 2>&1
    local rc=$?
    tail -n 6 "$log" | sed 's/^/    /'
    if [ "$rc" -eq 0 ]; then report ok "$*"; else report FAIL "$* (exit $rc)"; fi
}

# As step, but parity.py's exit 2 (no BigQuery leg) is its own outcome, not a FAIL.
parity_step() {
    local cmd=(python3 scripts/parity.py)
    printf '\n$ %s\n' "${cmd[*]}"
    "${cmd[@]}" >"$log" 2>&1
    local rc=$?
    tail -n 6 "$log" | sed 's/^/    /'
    if [ "$rc" -eq 0 ]; then
        report ok "${cmd[*]}"
    elif [ "$rc" -eq 2 ]; then
        report n/a "${cmd[*]} (exit 2: parity NOT established, no BQ_KEYFILE)"
        parity_not_established=1
    else
        report FAIL "${cmd[*]} (exit $rc)"
    fi
}

step bash scripts/check_env.sh
step bash scripts/load_duckdb_sources.sh
step python3 scripts/check_portability.py
parity_step

elapsed_ds=$(( ($(date +%s%N) - started_ns) / 100000000 ))
wall="$((elapsed_ds / 10)).$((elapsed_ds % 10))s"

echo
if [ "$failures" -gt 0 ]; then
    echo "pre-pr: $failures step(s) FAILED"
    echo "pre-pr: $wall"
    exit 1
fi
if [ "$parity_not_established" -eq 1 ]; then
    echo "PARITY NOT ESTABLISHED (no BQ_KEYFILE)"
    echo "pre-pr: every other step ok, including the portability guardrail. Parity was not"
    echo "        established: set BQ_KEYFILE (a service-account key path) to also measure"
    echo "        every model on BigQuery and compare it with DuckDB (capped at 1 GB billed)."
    echo "pre-pr: $wall"
    exit 2
fi
echo "pre-pr: all steps ok"
echo "pre-pr: $wall"
exit 0
