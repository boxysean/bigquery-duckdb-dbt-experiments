#!/usr/bin/env bash
#
# Installs what the Spark leg needs and `uv sync` (the root project's dbt) does not:
#
#   1. JDK 21 (Eclipse Temurin)       -> $SPARK_PREFIX/jdk
#   2. pyspark 4.2.0                  -> $SPARK_PREFIX/venv   (ships the Spark jars,
#                                        spark-submit and beeline)
#   3. the BigQuery Python client     -> $SPARK_PREFIX/venv   (google-cloud-bigquery,
#      + pyarrow                         its Storage Read API client and pyarrow, for
#                                        scripts/load_spark_sources.py)
#
# Everything lands in SPARK_PREFIX (default ~/.local/spark) — no sudo, no system
# package manager, no Docker. Idempotent: each step first checks what is already
# there and does nothing when it is the right version.
#
#   scripts/install_prereqs.sh
#   SPARK_PREFIX=/tmp/fresh-spark scripts/install_prereqs.sh   # install somewhere else
#
# It does not start the endpoint; scripts/start_spark.sh (make start-spark) does.
# The BigQuery client shares the pyspark venv on purpose: one interpreter for every
# Python piece of the Spark leg. The root project's .venv is never touched.
#
set -euo pipefail

JDK_MAJOR="21"
PYSPARK_VERSION="4.2.0"
PYTHON_VERSION="3.12"
SPARK_PREFIX="${SPARK_PREFIX:-$HOME/.local/spark}"
JDK_DIR="$SPARK_PREFIX/jdk"
VENV="$SPARK_PREFIX/venv"
PY="$VENV/bin/python"

# Adoptium's API returns the current Temurin 21 GA build together with its sha256,
# so the hash is checked against the publisher's own value rather than one pinned here.
ADOPTIUM_ASSET_API="https://api.adoptium.net/v3/assets/latest/${JDK_MAJOR}/hotspot?architecture=x64&image_type=jdk&os=linux&vendor=eclipse"

arch=$(uname -m)
if [ "$arch" != "x86_64" ]; then
    printf 'this script only covers linux/x86_64; this machine is linux/%s.\n' "$arch" >&2
    exit 1
fi
command -v uv >/dev/null 2>&1 || { printf 'uv not found on PATH; install it first (https://docs.astral.sh/uv/).\n' >&2; exit 1; }

mkdir -p "$SPARK_PREFIX"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# --- 1. JDK 21 ---------------------------------------------------------------
if [ -x "$JDK_DIR/bin/java" ] && "$JDK_DIR/bin/java" -version 2>&1 | grep -q "version \"$JDK_MAJOR\."; then
    printf '[1/3] JDK %s already installed: %s\n' "$JDK_MAJOR" "$("$JDK_DIR/bin/java" -version 2>&1 | sed -n 2p)"
else
    printf '[1/3] downloading Temurin JDK %s\n' "$JDK_MAJOR"
    curl -fsSL -o "$work/assets.json" "$ADOPTIUM_ASSET_API"
    read -r link sha < <(python3 -c '
import json, sys
pkg = json.load(open(sys.argv[1]))[0]["binary"]["package"]
print(pkg["link"], pkg["checksum"])' "$work/assets.json")
    curl -fsSL -o "$work/jdk.tar.gz" "$link"
    printf '%s  %s\n' "$sha" "$work/jdk.tar.gz" | sha256sum -c - >/dev/null || {
        printf 'sha256 mismatch for %s — refusing to install it.\n' "$link" >&2; exit 1; }
    mkdir -p "$work/jdk"
    tar xzf "$work/jdk.tar.gz" -C "$work/jdk" --strip-components=1
    rm -rf "$JDK_DIR"
    mv "$work/jdk" "$JDK_DIR"
    printf '      installed %s (%s)\n' "$JDK_DIR" "$("$JDK_DIR/bin/java" -version 2>&1 | sed -n 2p)"
fi

# --- 2. pyspark 4.2.0 --------------------------------------------------------
have_pyspark=$("$PY" -c 'import pyspark; print(pyspark.__version__)' 2>/dev/null || true)
if [ "$have_pyspark" = "$PYSPARK_VERSION" ]; then
    printf '[2/3] pyspark %s already installed in %s\n' "$PYSPARK_VERSION" "$VENV"
else
    printf '[2/3] installing pyspark==%s into %s (found: %s)\n' "$PYSPARK_VERSION" "$VENV" "${have_pyspark:-none}"
    [ -x "$PY" ] || uv venv --python "$PYTHON_VERSION" "$VENV"
    uv pip install --python "$PY" "pyspark==$PYSPARK_VERSION"
fi

# --- 3. the BigQuery client for the loader -----------------------------------
if "$PY" -c 'import google.cloud.bigquery, google.cloud.bigquery_storage, pyarrow' 2>/dev/null; then
    printf '[3/3] BigQuery client already installed: %s\n' "$("$PY" -c '
import google.cloud.bigquery as b, google.cloud.bigquery_storage as s, pyarrow as p
print(f"google-cloud-bigquery {b.__version__}, google-cloud-bigquery-storage {s.__version__}, pyarrow {p.__version__}")')"
else
    printf '[3/3] installing the BigQuery client + pyarrow into %s\n' "$VENV"
    uv pip install --python "$PY" 'google-cloud-bigquery[bqstorage]' pyarrow
fi

printf '\nnext: scripts/start_spark.sh (make start-spark), then scripts/check_env.sh\n'
