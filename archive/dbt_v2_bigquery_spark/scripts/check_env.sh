#!/usr/bin/env bash
#
# Prerequisite gate for BOTH targets of this project (spark and bigquery).
#
# `make spark`, `make parity` and `make pre-pr` depend on this script, and it is
# meant to be run on its own before anything else. It fails loudly: every missing
# prerequisite gets its own line saying what is missing and what to run instead,
# and the exit status is 1. It never half-succeeds.
#
#   scripts/check_env.sh
#
# The BigQuery credential is REPORTED (ok / n/a), never a failure: without one the
# Spark leg still runs, and `make bq` refuses with its own exit 2.
#
# Each binary can be overridden, which is how the failing path is demonstrated
# on a machine that has everything installed:
#
#   DBT_BIN=/nonexistent/dbt  scripts/check_env.sh   # -> exit 1
#   SPARK_PORT=10009          scripts/check_env.sh   # -> exit 1 (no endpoint there)
#
set -uo pipefail

# --- the versions this project is written against (see SPEC.md section 0) ------
DBT_PIN="dbt-oss 2.0.5"
DBT_PIN_RE="2\.0\."
JDK_MAJOR="21"
PYSPARK_PIN="4.2.0"

project_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$project_root" || exit 1

SPARK_PREFIX="${SPARK_PREFIX:-$HOME/.local/spark}"
SPARK_PORT="${SPARK_PORT:-10000}"
DEFAULT_BQ_KEYFILE="$HOME/.config/gcp/coreychimpbot-sa.json"
dbt_bin="${DBT_BIN:-$project_root/../../1_dbt_bigquery_duckdb/.venv/bin/dbt}"
java_bin="$SPARK_PREFIX/jdk/bin/java"
spark_py="$SPARK_PREFIX/venv/bin/python"

failures=0
ok()   { printf '  ok    %s\n' "$*"; }
na()   { printf '  n/a   %s\n' "$*"; }
fail() { printf '  FAIL  %s\n' "$*"; failures=$((failures + 1)); }

printf 'checking prerequisites in %s\n' "$project_root"

# --- 1. dbt v2 ---------------------------------------------------------------
if ! out=$("$dbt_bin" --version 2>&1); then
    fail "dbt not found at '$dbt_bin'. Install it with: uv sync (in the repository root)   [pin: $DBT_PIN]"
elif ! printf '%s' "$out" | grep -q "$DBT_PIN_RE"; then
    fail "dbt at '$dbt_bin' is not v2: $(printf '%s' "$out" | tr '\n' ' '). Expected $DBT_PIN. Fix: uv sync"
else
    ok "dbt v2 ($(printf '%s' "$out" | tr '\n' ' ' | sed 's/ *$//'))"
fi

# --- 2. the experimental-adapter gate ----------------------------------------
# Measured: without it every dbt command fails with InvalidConfig (dbt1005)
# "The 'spark' adapter is not yet supported by dbt".
if [ "${DBT_ALLOW_EXPERIMENTAL_ADAPTERS:-}" = "true" ]; then
    ok "DBT_ALLOW_EXPERIMENTAL_ADAPTERS=true"
else
    fail "DBT_ALLOW_EXPERIMENTAL_ADAPTERS is '${DBT_ALLOW_EXPERIMENTAL_ADAPTERS:-unset}', not 'true'. dbt-oss 2.0.5 refuses the spark adapter without it. Fix: export DBT_ALLOW_EXPERIMENTAL_ADAPTERS=true   [the Makefile exports it]"
fi

# --- 3. JDK 21 ---------------------------------------------------------------
if ! out=$("$java_bin" -version 2>&1); then
    fail "no JDK at '$java_bin'. Spark 4.2 needs JDK $JDK_MAJOR. Fix: scripts/install_prereqs.sh"
elif ! printf '%s' "$out" | grep -q "version \"$JDK_MAJOR\."; then
    fail "the JDK at '$java_bin' is '$(printf '%s' "$out" | head -n1)', not $JDK_MAJOR. Fix: scripts/install_prereqs.sh"
else
    ok "JDK $JDK_MAJOR ($(printf '%s' "$out" | sed -n 2p))"
fi

# --- 4. pyspark 4.2.0 (the Spark runtime, spark-submit and beeline) ----------
ver=$("$spark_py" -c 'import pyspark; print(pyspark.__version__)' 2>/dev/null || true)
if [ -z "$ver" ]; then
    fail "pyspark not importable from '$spark_py'. Fix: scripts/install_prereqs.sh   [pin: pyspark==$PYSPARK_PIN]"
elif [ "$ver" != "$PYSPARK_PIN" ]; then
    fail "pyspark in '$spark_py' is $ver, but this project pins $PYSPARK_PIN. Fix: scripts/install_prereqs.sh"
else
    ok "pyspark $ver ($SPARK_PREFIX/venv)"
fi

# --- 5. the loader's BigQuery client -----------------------------------------
if out=$("$spark_py" -c 'import google.cloud.bigquery as b, google.cloud.bigquery_storage, pyarrow as p; print(f"google-cloud-bigquery {b.__version__}, pyarrow {p.__version__}")' 2>/dev/null); then
    ok "loader client: $out"
else
    fail "the BigQuery client / pyarrow is not importable from '$spark_py'; scripts/load_spark_sources.py needs it. Fix: scripts/install_prereqs.sh"
fi

# --- 6. the Spark endpoint ---------------------------------------------------
if (exec 3<>"/dev/tcp/127.0.0.1/$SPARK_PORT") 2>/dev/null; then
    ok "Spark Thrift endpoint reachable on 127.0.0.1:$SPARK_PORT"
else
    fail "nothing listens on 127.0.0.1:$SPARK_PORT; the spark target has no endpoint (dbt-oss has no in-process 'session' method). Fix: scripts/start_spark.sh   [or make start-spark]"
fi

# --- 7. the project files dbt needs to find ----------------------------------
for f in dbt_project.yml profiles.yml; do
    if [ -f "$project_root/$f" ]; then
        ok "$f present"
    else
        fail "$f is missing from $project_root (it is committed; a missing file means a broken checkout)"
    fi
done

# --- 8. the BigQuery credential (reported, never a failure) -----------------
adc="$HOME/.config/gcloud/application_default_credentials.json"
keyfile="${BQ_KEYFILE:-}"
[ -z "$keyfile" ] && [ -f "$DEFAULT_BQ_KEYFILE" ] && keyfile="$DEFAULT_BQ_KEYFILE"
if [ -n "$keyfile" ] && [ -f "$keyfile" ]; then
    if [ -n "${BQ_KEYFILE:-}" ]; then src="BQ_KEYFILE from the environment"
    else src="BQ_KEYFILE unset, defaulted to ~/.config/gcp/coreychimpbot-sa.json"; fi
    ok "BigQuery credential: service-account key file ($src)"
elif [ -n "$keyfile" ]; then
    na "BigQuery credential: BQ_KEYFILE names a file that does not exist; the bigquery target and the loader will refuse (exit 2). The Spark leg is unaffected."
elif [ -n "${GOOGLE_APPLICATION_CREDENTIALS:-}" ] && [ -f "$GOOGLE_APPLICATION_CREDENTIALS" ]; then
    ok "BigQuery credential: GOOGLE_APPLICATION_CREDENTIALS key file"
elif [ -f "$adc" ]; then
    ok "BigQuery credential: gcloud application-default credentials ($adc)"
else
    na "BigQuery credential: none (no BQ_KEYFILE, no GOOGLE_APPLICATION_CREDENTIALS, no ADC). make bq and the loader will refuse with exit 2; the Spark leg needs the loaded sources, which need it once."
fi

if [ "$failures" -gt 0 ]; then
    printf '\n%d prerequisite check(s) FAILED. Nothing was run. See SPEC.md section 0.\n' "$failures"
    exit 1
fi

printf '\nall prerequisites present:\n'
printf '  make spark       load the real sources into Spark, then dbt build --target spark\n'
printf '  make bq          dbt build --target bigquery (needs the credential above)\n'
