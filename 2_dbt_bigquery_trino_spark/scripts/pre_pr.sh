#!/usr/bin/env bash
#
# The whole pre-PR routine of the BigQuery + Trino project, behind `make pre-pr`. CI
# (.github/workflows/2_dbt_bigquery_trino_spark.yml) runs exactly this, so a green local
# run predicts a green CI run.
#
#   1. scripts/check_env.sh                   prerequisites
#   2. ../scripts/check_model_trees.py        the same models as project 1 (no drift)
#   3. scripts/check_portability.py           both targets compile; no dialect leak
#   4. docker compose up --wait               the lakehouse: S3, Iceberg REST, Trino
#   5. render_fixture.py + Spark land_sources Spark lands the shared source dataset
#   6. dbt build --target trino               30 models + 168 tests on Trino
#   7. dbt run-operation polyglot_selfcheck   every Trino macro EXECUTED, value-checked
#   8. scripts/spark_interop.py               Spark reads every table, same profile
#
# Every step prints a banner, the tail of its output and ok / FAIL, then the next step
# runs (no `set -e`), so one run reports on all of them. Steps 5-8 are skipped (n/a)
# when the stack did not come up. Exit 0 all ok, 1 any FAIL, 2 nothing failed but a
# step could not run. The BigQuery target is compiled (step 3), never built: no
# credential is needed, and none is used even when one is present.
set -uo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root" || exit 1
export DBT_PROFILES_DIR="$root"
compose=(docker compose -f "$root/stack/compose.yml")
started=$(date +%s)
failures=0
not_run=0
stack_ok=0
log=$(mktemp)
trap 'rm -f "$log"' EXIT

step() { # <name> <command...>
    local name=$1; shift
    printf '\n$ %s\n' "$*"
    "$@" >"$log" 2>&1
    local rc=$?
    grep -v 'keyring module' "$log" | tail -n 6 | sed 's/^/    /'
    if [ "$rc" -eq 0 ]; then
        printf '  ok    %s\n' "$name"
    else
        printf '  FAIL  %s (exit %s)\n' "$name" "$rc"
        failures=$((failures + 1))
    fi
    return "$rc"
}
skip() { printf '\n  n/a   %s (the lakehouse stack is not up)\n' "$1"; not_run=1; }

step "prerequisites" bash scripts/check_env.sh
step "same models as project 1" .venv/bin/python ../scripts/check_model_trees.py
step "portability (both targets compile, no dialect leak)" .venv/bin/python scripts/check_portability.py
mkdir -p target/stack_io
step "lakehouse stack up" "${compose[@]}" up -d --wait && stack_ok=1

if [ "$stack_ok" -eq 1 ]; then
    step "fixture rendered from project 1's SQL" .venv/bin/python scripts/render_fixture.py
    step "Spark lands the sources (upstream producer)" "${compose[@]}" run --rm -T spark land_sources.py
    step "dbt build --target trino" .venv/bin/dbt build --target trino
    step "polyglot self-check executed on Trino" .venv/bin/dbt run-operation polyglot_selfcheck --target trino
    step "Spark reads every table dbt built (downstream consumer)" .venv/bin/python scripts/spark_interop.py
else
    for s in "fixture" "Spark lands the sources" "dbt build --target trino" "polyglot self-check" "Spark interop"; do
        skip "$s"
    done
fi

wall=$(( $(date +%s) - started ))
echo
if [ "$failures" -gt 0 ]; then
    echo "pre-pr: $failures step(s) FAILED"; echo "pre-pr: ${wall}s"; exit 1
fi
if [ "$not_run" -eq 1 ]; then
    echo "pre-pr: NOT ESTABLISHED: the lakehouse steps did not run"; echo "pre-pr: ${wall}s"; exit 2
fi
echo "pre-pr: all steps ok"
echo "pre-pr: ${wall}s"
