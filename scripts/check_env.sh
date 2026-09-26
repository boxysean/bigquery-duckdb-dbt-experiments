#!/usr/bin/env bash
#
# Prerequisite gate for BOTH targets of this project.
#
# `make duck`, `make bq` and `make parity` all depend on this script, and it is
# meant to be run on its own before anything else. It fails loudly: every missing
# prerequisite gets its own line saying what is missing and what to run instead,
# and the exit status is 1. It never half-succeeds.
#
#   scripts/check_env.sh
#
# Each binary can be overridden, which is how the failing path is demonstrated
# on a machine that has everything installed:
#
#   DUCKDB_BIN=/nonexistent/duckdb scripts/check_env.sh   # -> exit 1
#   DBC_BIN=/nonexistent/dbc       scripts/check_env.sh   # -> exit 1
#
set -uo pipefail

# --- the versions this project is written against (see README) ---------------
DBT_PIN="dbt-oss 2.0.5"        # `uv sync` installs it from pyproject.toml
DBT_PIN_RE="2\.0\."
DUCKDB_PIN="DuckDB 1.5.x"      # the engine behind the DuckDB target
DUCKDB_PIN_PREFIX="v1.5"
DBC_PIN="dbc 0.3.x"            # installs the DuckDB ADBC driver
DBC_PIN_PREFIX="v0.3"
DBC_DRIVER="duckdb"
COMMUNITY_EXTENSION="bigquery"

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root" || exit 1

failures=0
ok()   { printf '  ok    %s\n' "$*"; }
fail() { printf '  FAIL  %s\n' "$*"; failures=$((failures + 1)); }

# Prefer the project's own venv (created by `uv sync`) over PATH, so the gate
# reports on the interpreter the build will actually use.
resolve() { # <override> <path relative to repo> <name on PATH>
    if [ -n "$1" ]; then printf '%s\n' "$1"; return; fi
    if [ -x "$repo_root/$2" ]; then printf '%s\n' "$repo_root/$2"; return; fi
    command -v "$3" 2>/dev/null || printf '%s\n' "$3"
}

dbt_bin=$(resolve "${DBT_BIN:-}"       ".venv/bin/dbt"    "dbt")
dbc_bin=$(resolve "${DBC_BIN:-}"       ".venv/bin/dbc"    "dbc")
duckdb_bin=$(resolve "${DUCKDB_BIN:-}" ".venv/bin/duckdb" "duckdb")

printf 'checking prerequisites in %s\n' "$repo_root"

# --- 1. dbt v2 ---------------------------------------------------------------
if ! out=$("$dbt_bin" --version 2>&1); then
    fail "dbt not found at '$dbt_bin'. Install it with: uv sync   [pin: $DBT_PIN]"
elif ! printf '%s' "$out" | grep -q "$DBT_PIN_RE"; then
    fail "dbt at '$dbt_bin' is not v2: $(printf '%s' "$out" | tr '\n' ' '). Expected $DBT_PIN; dbt v1 cannot build this project. Fix: uv sync"
else
    ok "dbt v2 ($(printf '%s' "$out" | tr '\n' ' ' | sed 's/ *$//'))"
fi

# --- 2. dbc (driver manager) -------------------------------------------------
# Required for determinism, not decoration: with no dbc-installed driver, dbt
# silently falls back to its bundled DuckDB driver, which carries its own DuckDB
# build (1.5.4 when this was measured on 2026-09-26) instead of the pinned 1.5.x.
if ! out=$("$dbc_bin" --version 2>&1); then
    fail "dbc not found at '$dbc_bin'. Required: the dbc-installed DuckDB driver is what pins the engine version dbt runs (dbt's bundled driver carries its own DuckDB). Fix: scripts/install_prereqs.sh   [pin: $DBC_PIN]"
elif ! printf '%s' "$out" | grep -q "$DBC_PIN_PREFIX"; then
    fail "dbc at '$dbc_bin' reported '$(printf '%s' "$out" | tr '\n' ' ')' but this project is written against $DBC_PIN. Fix: scripts/install_prereqs.sh"
else
    ok "dbc $(printf '%s' "$out" | head -n1)"
fi

# --- 3. the DuckDB ADBC driver itself ---------------------------------------
if "$dbc_bin" --version >/dev/null 2>&1; then
    if list=$("$dbc_bin" list 2>&1) && printf '%s' "$list" | grep -qw "$DBC_DRIVER"; then
        ver=$(printf '%s' "$list" | awk -v d="$DBC_DRIVER" '$1 == d { print $2 }')
        ok "duckdb ADBC driver installed (version ${ver:-unknown})"
        if [ -n "$ver" ] && [ "${ver#1.5}" = "$ver" ]; then
            fail "the installed DuckDB driver is $ver, but the project pins $DUCKDB_PIN. Fix: dbc install duckdb"
        fi
    else
        fail "the DuckDB ADBC driver is not installed. Without it dbt uses its bundled driver and runs a different DuckDB version than this project pins. Fix: dbc install duckdb"
    fi
fi

# --- 4. the DuckDB engine (CLI) ---------------------------------------------
if ! out=$("$duckdb_bin" --version 2>&1); then
    fail "DuckDB not found at '$duckdb_bin'. The DuckDB target is pinned to $DUCKDB_PIN. Fix: scripts/install_prereqs.sh"
elif ! printf '%s' "$out" | grep -q "$DUCKDB_PIN_PREFIX"; then
    fail "DuckDB at '$duckdb_bin' is '$(printf '%s' "$out" | tr '\n' ' ')' but this project pins $DUCKDB_PIN. Fix: scripts/install_prereqs.sh"
else
    ok "duckdb CLI $(printf '%s' "$out" | tr '\n' ' ' | sed 's/ *$//')"
fi

# --- 5. the community extension ---------------------------------------------
# profiles.yml names it under extensions:, but dbt-oss 2.0.5 cannot declare a
# community repo there (see profiles.yml), and a bare name is only ever looked up
# in the CORE repository, where `bigquery` does not exist. So it has to be
# installed into DuckDB's extension cache beforehand.
if [ -x "$duckdb_bin" ]; then
    ext_query=$(printf 'SELECT extension_version FROM duckdb_extensions() WHERE extension_name = %s AND installed;\n' "'$COMMUNITY_EXTENSION'")
    if out=$(printf '%s' "$ext_query" | "$duckdb_bin" -list -noheader -init /dev/null ":memory:" 2>&1) && [ -n "$out" ]; then
        ok "duckdb community extension '$COMMUNITY_EXTENSION' installed (build $(printf '%s' "$out" | head -n1))"
    else
        fail "the DuckDB community extension '$COMMUNITY_EXTENSION' is NOT installed for this DuckDB. profiles.yml lists it under extensions:, and a bare name is only found in the CORE repo (HTTP 404). Fix: duckdb -c \"INSTALL $COMMUNITY_EXTENSION FROM community\"   [or scripts/install_prereqs.sh]"
    fi
fi

# --- 6. the project files dbt needs to find --------------------------------
for f in dbt_project.yml profiles.yml; do
    if [ -f "$repo_root/$f" ]; then
        ok "$f present"
    else
        fail "$f is missing from $repo_root (it is committed; a missing file means a broken checkout)"
    fi
done

if [ "$failures" -gt 0 ]; then
    printf '\n%d prerequisite check(s) FAILED. Nothing was run. See README.md > Prerequisites.\n' "$failures"
    exit 1
fi

printf '\nall prerequisites present. The duckdb target is ready:\n'
printf '  make duck        # dbt build against the local DuckDB file\n'
printf '  make bq          # configured, but needs Google credentials (see README)\n'
