#!/usr/bin/env bash
#
# Compile the project on BOTH targets, in one command, behind `make ci-compile`:
#
#   1. scripts/check_env.sh                     prerequisites
#   2. scripts/load_duckdb_sources.sh           the DuckDB fixture (dev.duckdb)
#   3. dbt compile --target duckdb
#   4. dbt compile --target bigquery            only when a credential is named
#   5. scripts/check_portability.py             the guardrail
#
# Why: this is the one definition of "compile both targets". CI runs it through
# `make ci-compile` on every push to main and every pull request
# (.github/workflows/ci.yml), and a person runs the identical command before opening
# a PR, so CI is a gate and not a surprise.
#
# Step 5 is not decoration. A raw `try_cast(...)` in a model, or a
# `{% if target.type == 'duckdb' %}` branch, compiles cleanly on both targets, so
# steps 3 and 4 cannot catch either; only the guardrail does. Step 2 is not optional
# either: check_portability.py refuses to run without dev.duckdb (exit 2).
#
# Step 4 is gated on a credential, not on dbt's exit code: measured on 2026-09-29,
# `dbt compile --target bigquery` exits 0 with NO Google credentials at all. It issues
# no query and does not authenticate. Trusting its exit code alone would report a
# BigQuery leg that was never established. So:
#   * neither BQ_KEYFILE nor GOOGLE_APPLICATION_CREDENTIALS set  -> n/a, not run
#   * BQ_KEYFILE set but the file is missing or empty             -> FAIL
#   * BQ_KEYFILE set but the file has no "client_email" (it is not
#     a service-account JSON key)                                 -> FAIL
#   * otherwise BQ_AUTH_METHOD defaults to service-account and the compile runs;
#     a non-zero dbt exit is a FAIL.
# profiles.yml reads BQ_KEYFILE and BQ_AUTH_METHOD from the environment itself, so no
# key is ever copied into the repository. With only GOOGLE_APPLICATION_CREDENTIALS
# set, the profile's default method (oauth, Application Default Credentials) reads it.
# Even when it runs, the compile proves the project renders for BigQuery with a key
# of the right shape; it does not prove a live connection or a build (`make bq`).
#
# Every step prints `ok`, `n/a` or `FAIL` with the command it ran and keeps going, so
# one run reports on all of them. There is deliberately no `set -e`.
#
# Exit status
#   0  every step ok, both targets compiled
#   1  a real finding: any step failed (this wins over exit 2 below)
#   2  every other step ok, but step 4 was n/a: no credential, so the BigQuery compile
#      was NOT established and this run says nothing about the BigQuery target.
#      Never a silent pass.
#
# Cost: nothing. `dbt compile` bills nothing on DuckDB, and on BigQuery it issues no
# query; the BigQuery leg only runs at all when a key is present.
#
# The last line is the total wall time, `ci-compile: <N.N>s`, for recording.
#
set -uo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root" || exit 1
export DBT_PROFILES_DIR="$repo_root"

started_ns=$(date +%s%N)
failures=0
oks=0
bq_not_established=0
duck_counts=""
bq_counts=""
guardrail_counts=""
log=$(mktemp)
trap 'rm -f "$log"' EXIT

report() { # <status> <command>
    case "$1" in
        ok)  printf '  ok    %s\n' "$2"
             oks=$((oks + 1)) ;;
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

# The runner's own numbers from the last step's log, e.g. dbt's Processed:/Summary:.
quote() { # <extended regex>
    grep -E "$1" "$log" | sed 's/^/    /'
}

banner() {
    local bang
    bang=$(printf '!%.0s' $(seq 1 78))
    printf '%s\n' "$bang"
    printf 'NOT ESTABLISHED: BigQuery compile NOT performed (no BQ_SA_KEY secret)\n'
    printf '  `dbt compile --target bigquery` was NOT run: this run says nothing about the\n'
    printf '  BigQuery target. Add the BQ_SA_KEY repository secret in GitHub Actions, or\n'
    printf '  export BQ_KEYFILE locally, to make this leg real. The DuckDB leg is unaffected.\n'
    printf '%s\n' "$bang"
}

step bash scripts/check_env.sh
step bash scripts/load_duckdb_sources.sh

step .venv/bin/dbt compile --target duckdb
duck_counts=$(quote '^(Processed|Summary):')

# --- the BigQuery leg, gated on a credential ---------------------------------
bq_cmd=".venv/bin/dbt compile --target bigquery"
if [ -z "${BQ_KEYFILE:-}" ] && [ -z "${GOOGLE_APPLICATION_CREDENTIALS:-}" ]; then
    printf '\n$ %s\n' "$bq_cmd"
    report n/a "$bq_cmd — NOT performed (no BQ_SA_KEY secret / BQ_KEYFILE not set)"
    banner
    bq_not_established=1
elif [ -n "${BQ_KEYFILE:-}" ] && [ ! -s "$BQ_KEYFILE" ]; then
    printf '\n$ %s\n' "$bq_cmd"
    report FAIL "$bq_cmd — BQ_KEYFILE is set but '$BQ_KEYFILE' is missing or empty"
elif [ -n "${BQ_KEYFILE:-}" ] && ! grep -q '"client_email"' "$BQ_KEYFILE"; then
    printf '\n$ %s\n' "$bq_cmd"
    report FAIL "$bq_cmd — '$BQ_KEYFILE' has no \"client_email\": not a service-account JSON key"
elif [ -z "${BQ_KEYFILE:-}" ] && [ ! -s "$GOOGLE_APPLICATION_CREDENTIALS" ]; then
    printf '\n$ %s\n' "$bq_cmd"
    report FAIL "$bq_cmd — GOOGLE_APPLICATION_CREDENTIALS is set but '$GOOGLE_APPLICATION_CREDENTIALS' is missing or empty"
else
    # A key file only means service-account auth; without one the profile's default
    # (oauth / ADC) is what reads GOOGLE_APPLICATION_CREDENTIALS.
    if [ -n "${BQ_KEYFILE:-}" ]; then
        export BQ_AUTH_METHOD="${BQ_AUTH_METHOD:-service-account}"
    fi
    step .venv/bin/dbt compile --target bigquery
    bq_counts=$(quote '^(Processed|Summary):')
fi

step python3 scripts/check_portability.py
guardrail_counts=$(quote '^(compiled files checked:|PORTABLE$|NOT PORTABLE:)')

elapsed_ds=$(( ($(date +%s%N) - started_ns) / 100000000 ))
wall="$((elapsed_ds / 10)).$((elapsed_ds % 10))s"

echo
echo "ci-compile: $oks step(s) ok"
echo "ci-compile: DuckDB compile:"
printf '%s\n' "${duck_counts:-    (no Processed:/Summary: line in its output)}"
if [ "$bq_not_established" -eq 1 ]; then
    echo "ci-compile: BigQuery compile: not performed (no credential)"
elif [ -n "$bq_counts" ]; then
    echo "ci-compile: BigQuery compile:"
    printf '%s\n' "$bq_counts"
else
    echo "ci-compile: BigQuery compile: FAIL (see above)"
fi
echo "ci-compile: portability guardrail:"
printf '%s\n' "${guardrail_counts:-    (no summary in its output; see the FAIL line above)}"
echo

if [ "$failures" -gt 0 ]; then
    echo "ci-compile: $failures step(s) FAILED"
    echo "ci-compile: $wall"
    exit 1
fi
if [ "$bq_not_established" -eq 1 ]; then
    banner
    echo "ci-compile: every other step ok, including the DuckDB compile and the portability"
    echo "            guardrail. The BigQuery compile was NOT established (exit 2)."
    echo "ci-compile: $wall"
    exit 2
fi
echo "ci-compile: all steps ok, both targets compiled"
echo "ci-compile: $wall"
exit 0
