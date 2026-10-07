#!/usr/bin/env bash
#
# Assert every prerequisite of the BigQuery + Trino project, failing loudly on any gap.
# Exit 0 all present, 1 something missing. The BigQuery credential is REPORTED, not
# required: the trino target and the local lakehouse need no cloud account.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

fail=0
ok()  { printf '  ok    %s\n' "$1"; }
bad() { printf '  FAIL  %s\n' "$1"; fail=1; }

echo "checking prerequisites in $(pwd)"
[ -x .venv/bin/dbt ] && ok "dbt: $(.venv/bin/dbt --version 2>/dev/null | grep -m1 installed | awk '{print $NF}') (dbt-core)" \
    || bad "dbt not installed: run make setup (uv sync)"
.venv/bin/python -c 'import dbt.adapters.trino, dbt.adapters.bigquery' 2>/dev/null \
    && ok "adapters: dbt-trino and dbt-bigquery importable" || bad "dbt-trino / dbt-bigquery missing: make setup"
.venv/bin/python -c 'import duckdb, trino' 2>/dev/null \
    && ok "tooling: duckdb (fixture renderer) and trino (client) importable" || bad "dev tooling missing: make setup"
command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1 \
    && ok "docker: daemon reachable" || bad "docker daemon not reachable (the lakehouse runs in Docker)"
docker compose version >/dev/null 2>&1 && ok "docker compose: $(docker compose version --short)" \
    || bad "docker compose plugin missing"
command -v openssl >/dev/null 2>&1 && ok "openssl (throwaway key for the credential-free BigQuery compile)" \
    || bad "openssl missing"
for j in iceberg-spark-runtime-4.0_2.13-1.10.0.jar iceberg-aws-bundle-1.10.0.jar; do
    [ -f "stack/spark/jars/$j" ] && ok "spark jar: $j" || bad "spark jar missing: $j (make jars)"
done
[ -f ../1_dbt_bigquery_duckdb/scripts/fixtures/thelook_ecommerce.sql ] \
    && ok "shared fixture: ../1_dbt_bigquery_duckdb/scripts/fixtures/thelook_ecommerce.sql" \
    || bad "project 1's fixture is missing (the shared source dataset)"
if [ -n "${BQ_KEYFILE:-}" ] && [ -f "${BQ_KEYFILE}" ]; then
    echo "  info  BigQuery: BQ_KEYFILE set; the bigquery target can build"
else
    echo "  info  BigQuery: no BQ_KEYFILE; the bigquery target is compile-only here (not a failure)"
fi
[ "$fail" -eq 0 ] && echo "check-env: all prerequisites present" || echo "check-env: prerequisites MISSING"
exit "$fail"
