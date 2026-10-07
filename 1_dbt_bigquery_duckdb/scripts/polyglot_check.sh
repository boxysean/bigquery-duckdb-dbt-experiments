#!/usr/bin/env bash
#
# The whole macro layer in one command (SPEC section 7.4), behind `make polyglot`:
#
#   1. scripts/check_env.sh                     prerequisites
#   2. scripts/load_duckdb_sources.sh           the DuckDB fixture
#   3. polyglot_selfcheck on DuckDB             every macro executed and compared
#   4. polyglot_render on DuckDB and BigQuery   rendered SQL, teed to
#                                               target/polyglot_render_<target>.txt
#   5. the decimal ceiling on DuckDB            MUST fail with the ceiling message
#   6. scripts/check_portability.py             the guardrail
#   7. scripts/check_portability.py --demo      the guardrail can fail, then passes
#
# Every step prints `ok` or `FAIL` with the command it ran and keeps going, so one
# run reports on all of them. There is deliberately no `set -e`: each step's own
# exit status is what gets reported. Exit 0 only when every step is `ok`.
#
set -uo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root" || exit 2
export DBT_PROFILES_DIR="$repo_root"
DBT=.venv/bin/dbt

CEILING_MESSAGE="DuckDB DECIMAL is capped at 38 digits"

failures=0
log=$(mktemp)
trap 'rm -f "$log"' EXIT

report() { # <status> <command>
    if [ "$1" = ok ]; then
        printf '  ok    %s\n' "$2"
    else
        printf '  FAIL  %s\n' "$2"
        failures=$((failures + 1))
    fi
}

# Run a command, show the tail of its output, report ok iff it exits 0.
step() { # <command...>
    printf '\n$ %s\n' "$*"
    "$@" >"$log" 2>&1
    local rc=$?
    tail -n 6 "$log" | sed 's/^/    /'
    if [ "$rc" -eq 0 ]; then report ok "$*"; else report FAIL "$* (exit $rc)"; fi
}

# polyglot_render for one target, teed in full to target/polyglot_render_<target>.txt.
render_step() { # <target>
    local out="target/polyglot_render_$1.txt"
    local cmd=("$DBT" run-operation polyglot_render --target "$1")
    printf '\n$ %s | tee %s\n' "${cmd[*]}" "$out"
    mkdir -p target
    "${cmd[@]}" 2>&1 | tee "$out" | grep -c "render .* $1 :: " | sed 's/^/    render lines: /'
    local rc=${PIPESTATUS[0]}
    if [ "$rc" -eq 0 ]; then report ok "${cmd[*]}"; else report FAIL "${cmd[*]} (exit $rc)"; fi
}

# The expected failure: decimal_type(77,38) must be refused on DuckDB, with the
# ceiling message. Succeeding, or failing for any other reason, is a FAIL.
ceiling_step() {
    local cmd=("$DBT" run-operation polyglot_render --args '{include_bignumeric: true}' --target duckdb)
    printf '\n$ %s   (expected to fail)\n' "${cmd[*]}"
    "${cmd[@]}" >"$log" 2>&1
    local rc=$?
    grep -m 1 -o "decimal_type(77, 38): $CEILING_MESSAGE[^.]*" "$log" | sed 's/^/    /'
    if [ "$rc" -ne 0 ] && grep -q "$CEILING_MESSAGE" "$log"; then
        report ok "${cmd[*]} (failed as expected with the decimal-ceiling message)"
    elif [ "$rc" -eq 0 ]; then
        report FAIL "${cmd[*]} (exit 0: the decimal ceiling was NOT enforced)"
    else
        tail -n 6 "$log" | sed 's/^/    /'
        report FAIL "${cmd[*]} (exit $rc, but not with the decimal-ceiling message)"
    fi
}

step bash scripts/check_env.sh
step bash scripts/load_duckdb_sources.sh
step "$DBT" run-operation polyglot_selfcheck --target duckdb
render_step duckdb
render_step bigquery
ceiling_step
step python3 scripts/check_portability.py
step python3 scripts/check_portability.py --demo

echo
if [ "$failures" -eq 0 ]; then
    echo "polyglot check: all steps ok"
    exit 0
fi
echo "polyglot check: $failures step(s) FAILED"
exit 1
