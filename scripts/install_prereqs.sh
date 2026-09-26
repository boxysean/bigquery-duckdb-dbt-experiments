#!/usr/bin/env bash
#
# Installs the four prerequisites `uv sync` cannot install for you:
#
#   1. dbc                        (the ADBC driver manager)
#   2. the DuckDB ADBC driver     (dbc install duckdb — pins the engine version)
#   3. the DuckDB CLI             (the 1.5.x engine this project is pinned to)
#   4. the community `bigquery`
#      DuckDB extension           (dbt-oss cannot declare a community repo in
#                                   profiles.yml, so it is installed here)
#
# Everything lands in PREFIX (default ~/.local/bin) — no sudo, no system package
# manager. Re-running is safe.
#
#   scripts/install_prereqs.sh
#   PREFIX=/tmp/fresh-bin scripts/install_prereqs.sh   # install somewhere else
#
# This is the one piece of the project that needs the network *and* writes
# outside the repository, which is exactly why it is a script you run yourself
# rather than something a build target does behind your back.
#
set -euo pipefail

DUCKDB_VERSION="1.5.5"   # README > Pinned versions
DBC_VERSION="0.3.0"

# sha256 of the official release assets. dbc publishes a checksums file next to
# its release (verified against it when this script was written); DuckDB ships
# the asset itself for a tagged release, so the hash below is the hash of the
# bytes at the URL below. A mismatch aborts the install.
DBC_ASSET_SHA256="bb575a9f522062a122fce417de29489d8c7b2c2fb415e3ef9eb8a0c4147b6270"
DUCKDB_CLI_SHA256="08c0ca117111fcede14239d0093792352befdc174218c344d232c13279643d05"

DBC_URL="https://github.com/columnar-tech/dbc/releases/download/v${DBC_VERSION}/dbc-linux-amd64-${DBC_VERSION}.tar.gz"
DUCKDB_CLI_URL="https://github.com/duckdb/duckdb/releases/download/v${DUCKDB_VERSION}/duckdb_cli-linux-amd64.zip"

PREFIX="${PREFIX:-$HOME/.local/bin}"
export PATH="$PREFIX:$PATH"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

arch=$(uname -m)
if [ "$arch" != "x86_64" ]; then
    printf 'this script only covers linux/x86_64; this machine is linux/%s.\n' "$arch" >&2
    printf 'Install dbc and the DuckDB CLI by hand (see README > Prerequisites), then run scripts/check_env.sh.\n' >&2
    exit 1
fi

mkdir -p "$PREFIX"

verify() { # <file> <expected sha256>
    printf '%s  %s\n' "$2" "$1" | sha256sum -c - >/dev/null || {
        printf 'sha256 mismatch for %s — refusing to install it.\n' "$1" >&2
        exit 1
    }
}

# --- 1 + 2. dbc, then the driver it installs --------------------------------
if command -v dbc >/dev/null 2>&1; then
    printf '[1/4] dbc already on PATH: %s\n' "$(dbc --version)"
else
    printf '[1/4] downloading dbc %s\n' "$DBC_VERSION"
    curl -fsSL -o "$work/dbc.tar.gz" "$DBC_URL"
    verify "$work/dbc.tar.gz" "$DBC_ASSET_SHA256"
    tar xzf "$work/dbc.tar.gz" -C "$work"
    install -m 755 "$work/dbc" "$PREFIX/dbc"
    printf '      installed %s/dbc (%s)\n' "$PREFIX" "$("$PREFIX/dbc" --version)"
fi

printf '[2/4] installing the DuckDB ADBC driver (this is what pins the DuckDB engine version)\n'
dbc install duckdb

# --- 3. the DuckDB CLI ------------------------------------------------------
if command -v duckdb >/dev/null 2>&1; then
    printf '[3/4] duckdb already on PATH: %s\n' "$(duckdb --version)"
else
    printf '[3/4] downloading DuckDB CLI %s\n' "$DUCKDB_VERSION"
    curl -fsSL -o "$work/duckdb.zip" "$DUCKDB_CLI_URL"
    verify "$work/duckdb.zip" "$DUCKDB_CLI_SHA256"
    unzip -q "$work/duckdb.zip" -d "$work/duckdb"
    install -m 755 "$work/duckdb/duckdb" "$PREFIX/duckdb"
    printf '      installed %s/duckdb (%s)\n' "$PREFIX" "$("$PREFIX/duckdb" --version)"
fi

# --- 4. the community `bigquery` extension ----------------------------------
# profiles.yml names it under extensions:, but dbt-oss 2.0.5 rejects the
# documented `{ name: bigquery, repo: community }` form (InvalidConfig dbt1005:
# "extensions: item 2 must be a string") and resolves a bare name in the CORE
# repository only, where `bigquery` does not exist (HTTP 404). Installing it here
# puts it in DuckDB's extension cache, after which the plain name loads it.
printf '[4/4] installing the community %s extension\n' "bigquery"
printf 'INSTALL bigquery FROM community;\n' | duckdb ":memory:"

printf '\nstep 5 (dbt itself) is separate: run `uv sync` in the repository root.\n'
printf 'then verify everything with: scripts/check_env.sh\n'
