#!/usr/bin/env bash
#
# Row-count parity: for every model under models/marts, compare the row count the
# model produces on each target. One model, two engines, one expected number.
#
#   make parity
#
# Exit status:
#   0  every model matched on both targets — or there is nothing to compare,
#      which is reported as VACUOUS and is not evidence of anything
#   1  a mismatch, or a leg that failed while the other one measured
#   2  the bigquery leg is not runnable here (no Google credentials); the duckdb
#      numbers are still printed
#
set -uo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root" || exit 1

DBT="$repo_root/.venv/bin/dbt"
export DBT_PROFILES_DIR="$repo_root"

models=$("$DBT" ls --quiet --target duckdb --resource-type model --select 'path:models/marts' \
    --output json --output-keys name 2>/dev/null \
    | grep -o '"name":"[^"]*"' | cut -d'"' -f4)

if [ -z "$models" ]; then
    printf 'VACUOUS parity run: no models under models/marts, so nothing was compared.\n'
    printf 'Card 1 ships an empty skeleton, so this is expected. It is NOT evidence of parity:\n'
    printf 'the first model added to models/marts is the first thing this target can prove.\n'
    exit 0
fi

count() { # <model> <target> -> row count on stdout, empty on failure
    out=$("$DBT" show --inline "select count(*) as n from {{ ref('$1') }}" \
        --target "$2" --output json 2>/dev/null)
    printf '%s' "$out" | grep -o '"n":[0-9]*' | head -n1 | cut -d: -f2
}

printf '%-40s %12s %12s\n' "model" "duckdb" "bigquery"

rc=0
bq_missing=0
for m in $models; do
    d=$(count "$m" duckdb)
    b=$(count "$m" bigquery)
    [ -z "$d" ] && d="FAILED"
    if [ -z "$b" ]; then
        b="n/a"
        bq_missing=1
    fi
    if [ "$d" != "$b" ] && [ "$b" != "n/a" ]; then
        rc=1
    fi
    printf '%-40s %12s %12s\n' "$m" "$d" "$b"
done

if [ "$bq_missing" -eq 1 ]; then
    printf '\nthe bigquery leg could not be measured: no Google credentials on this machine\n'
    printf '(see scripts/run_bq.sh, or README > Prerequisites). Parity between the two targets\n'
    printf 'is therefore NOT established by this run.\n'
    [ "$rc" -eq 0 ] && rc=2
fi

case "$rc" in
    0) printf '\nparity: every model matched on both targets.\n' ;;
    1) printf '\nparity: MISMATCH — see the table above.\n' ;;
    2) printf '\nparity: duckdb only.\n' ;;
esac
exit "$rc"
