#!/usr/bin/env bash
#
# Load the REAL bigquery-public-data.thelook_ecommerce into dev.duckdb (Transport A).
#
#   scripts/load_duckdb_real_sources.sh                   # or: make fixtures-real
#   scripts/load_duckdb_real_sources.sh --raw-timestamps  # the D2 probe, scratch file
#
# The value-parity card (SPEC-value-parity.md) needs both legs to read the same rows.
# This replaces the fixture in dev.thelook_ecommerce.* with the seven real tables,
# copied through the community `bigquery` extension (Storage Read API: table reads,
# not query jobs, so maximum_bytes_billed is not involved). Every column the real
# table has is copied, including the two GEOMETRY columns the fixture lacks; staging
# selects named columns, so extra source columns are inert.
#
# Timestamps (D2). The source contract (models/staging/_thelook__sources.yml) says a
# timestamp is an absolute instant, TIMESTAMPTZ on DuckDB, and the DuckDB branch of
# to_utc_timestamp (macros/polyglot/casting.sql) relies on it. The extension hands a
# BigQuery TIMESTAMP back as a zone-less TIMESTAMP (analyses/transport_a/README.md:179),
# which the macro would then read in the *session* time zone. So every TIMESTAMP column
# is delivered as TIMESTAMPTZ via to_timestamp(epoch_us(c) / 1000000.0), and the loader
# proves, row by row against the raw copy, that no instant moved. --raw-timestamps
# skips the mapping and loads what the extension returns, into a scratch file (never
# dev.duckdb), so the gap can be measured: the probe at the end reports how many rows
# the macro would shift and by how much.
#
# Per table it prints local rows vs BigQuery's numRows (table metadata), and the wall
# time of the transfer and of the mapping. Any missing prerequisite, row-count mismatch
# or moved instant -> exit 1. Everything printed also goes to $LOG, raw.
#
# Environment:
#   BQ_KEYFILE          service-account key file (required; the path is passed to
#                       DuckDB on stdin and redacted from the output, never printed)
#   BQ_DATA_PROJECT     default bigquery-public-data
#   BQ_BILLING_PROJECT  default coreychimpbot
#   DUCKDB_BIN          default: duckdb on PATH
#   DUCKDB_DB           default dev.duckdb; with --raw-timestamps target/raw_timestamps.duckdb
#   LOG                 default analyses/value_parity/logs/loader.log
#                       (loader-raw-timestamps.log with --raw-timestamps)
#   PROBE_TZ            an extra session time zone for the D2 probe (optional)
#
set -uo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root" || exit 1

raw=0
for arg in "$@"; do
    case "$arg" in
        --raw-timestamps) raw=1 ;;
        -h|--help) sed -n '2,/^set -uo/p' "${BASH_SOURCE[0]}" | sed '$d; s/^# \{0,1\}//'; exit 0 ;;
        *) printf 'FAIL  unknown argument: %s\n' "$arg" >&2; exit 1 ;;
    esac
done

DUCKDB_BIN=${DUCKDB_BIN:-duckdb}
BQ_DATA_PROJECT=${BQ_DATA_PROJECT:-bigquery-public-data}
BQ_BILLING_PROJECT=${BQ_BILLING_PROJECT:-coreychimpbot}
if [ "$raw" -eq 1 ]; then
    DUCKDB_DB=${DUCKDB_DB:-$repo_root/target/raw_timestamps.duckdb}
    LOG=${LOG:-$repo_root/analyses/value_parity/logs/loader-raw-timestamps.log}
else
    DUCKDB_DB=${DUCKDB_DB:-$repo_root/dev.duckdb}
    LOG=${LOG:-$repo_root/analyses/value_parity/logs/loader.log}
fi
TABLES=(distribution_centers products users inventory_items orders order_items events)

mkdir -p "$(dirname "$LOG")" "$(dirname "$DUCKDB_DB")"
exec > >(tee "$LOG") 2>&1

fail() { printf 'FAIL  %s\n' "$*"; exit 1; }
now() { date +%s.%N; }
secs() { awk -v a="$1" -v b="$2" 'BEGIN { printf "%.2f", b - a }'; }
# The key path is not a secret, but the logs are committed: keep it out of them.
redact() { if [ -n "${BQ_KEYFILE:-}" ]; then sed "s|$BQ_KEYFILE|\$BQ_KEYFILE|g"; else cat; fi; }
# Local-only query: pipe-separated rows, no header.
query() { "$DUCKDB_BIN" -bail -init /dev/null -noheader -list -separator '|' "$DUCKDB_DB" -c "$1"; }

# ------------------------------------------------------------------ prerequisites
command -v "$DUCKDB_BIN" >/dev/null 2>&1 \
    || fail "DuckDB CLI not found ($DUCKDB_BIN). Run \`make setup\` or set DUCKDB_BIN."
command -v python3 >/dev/null 2>&1 || fail "python3 not found"
command -v openssl >/dev/null 2>&1 || fail "openssl not found (scripts/bq_table_meta.py signs the token with it)"
[ -n "${BQ_KEYFILE:-}" ] || fail "BQ_KEYFILE is not set (the service-account key file for BigQuery)"
[ -r "$BQ_KEYFILE" ] || fail "BQ_KEYFILE does not name a readable file"
ext=$("$DUCKDB_BIN" -init /dev/null -noheader -list -separator '|' :memory: -c \
      "select extension_version, installed_from from duckdb_extensions()
       where extension_name = 'bigquery' and installed")
[ -n "$ext" ] || fail "the community bigquery extension is not installed (duckdb -c \"INSTALL bigquery FROM community\")"
if [ "$raw" -eq 1 ]; then
    real_db=$(realpath -m "$repo_root/dev.duckdb")
    [ "$(realpath -m "$DUCKDB_DB")" != "$real_db" ] \
        || fail "--raw-timestamps must not write dev.duckdb (the real load parity reads); pick another DUCKDB_DB"
fi

printf '# load_duckdb_real_sources.sh  %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf '# duckdb %s; bigquery extension %s\n' "$("$DUCKDB_BIN" --version)" "${ext//|/ from }"
printf '# data %s.thelook_ecommerce, billing %s, BQ_KEYFILE set\n' "$BQ_DATA_PROJECT" "$BQ_BILLING_PROJECT"
printf '# mode: %s\n' "$([ "$raw" -eq 1 ] && echo 'raw timestamps (what the extension returns)' \
                                         || echo 'D2: TIMESTAMP -> TIMESTAMPTZ via to_timestamp(epoch_us(c) / 1000000.0)')"
printf '# target %s (schema thelook_ecommerce); session TimeZone %s\n' \
    "${DUCKDB_DB#"$repo_root"/}" "$(query "select current_setting('TimeZone')")"

# ------------------------------------------------------------ BigQuery's numRows
printf '\nBigQuery table metadata (tables.get, not a query job):\n'
meta=$(BQ_DATA_PROJECT="$BQ_DATA_PROJECT" python3 scripts/bq_table_meta.py "${TABLES[@]}") \
    || fail "could not read table metadata from BigQuery"
declare -A num_rows num_bytes
while IFS='|' read -r t n b; do
    num_rows[$t]=$n; num_bytes[$t]=$b
    printf '  %-22s numRows %10s   numBytes %11s\n' "$t" "$n" "$b"
done <<< "$meta"

# ------------------------------------------------------------------------ load
# moved = timestamp values whose instant differs between the raw and the mapped copy,
# summed over the table's timestamp columns (ts_cols); it must be 0.
printf '\n%-22s %10s %10s %6s %11s %10s %8s %6s\n' table local numRows rows transfer_s map_s ts_cols moved
failed=0
started=$(now)
for t in "${TABLES[@]}"; do
    # The raw copy lands in <t>__raw on the D2 path, so the mapped table can be proved
    # against it; with --raw-timestamps it IS the table.
    dest=$([ "$raw" -eq 1 ] && echo "$t" || echo "${t}__raw")
    t0=$(now)
    out=$("$DUCKDB_BIN" -bail -init /dev/null "$DUCKDB_DB" 2>&1 <<SQL
LOAD bigquery;
CREATE TEMPORARY SECRET bq_data (TYPE bigquery, SCOPE 'bq://$BQ_DATA_PROJECT',
                                 SERVICE_ACCOUNT_PATH '$BQ_KEYFILE');
CREATE SCHEMA IF NOT EXISTS thelook_ecommerce;
CREATE OR REPLACE TABLE thelook_ecommerce."$dest" AS
SELECT * FROM bigquery_scan('$BQ_DATA_PROJECT.thelook_ecommerce.$t',
                            billing_project := '$BQ_BILLING_PROJECT');
SQL
    ) || { printf '%s\n' "$out" | redact; fail "transfer of $t failed"; }
    t1=$(now)

    map_s=- n_ts=- moved_total=-
    if [ "$raw" -eq 0 ]; then
        ts_cols=$(query "select column_name from information_schema.columns
                         where table_catalog = current_database() and table_schema = 'thelook_ecommerce'
                           and table_name = '${t}__raw' and data_type = 'TIMESTAMP'
                         order by ordinal_position")
        replace=$(for c in $ts_cols; do printf 'to_timestamp(epoch_us("%s") / 1000000.0) AS "%s", ' "$c" "$c"; done)
        select="SELECT *$([ -n "$replace" ] && printf ' REPLACE (%s)' "${replace%, }") FROM thelook_ecommerce.\"${t}__raw\""
        query "CREATE OR REPLACE TABLE thelook_ecommerce.\"$t\" AS $select" >/dev/null \
            || fail "mapping $t failed"
        n_ts=0 moved_total=0
        # The proof that no instant moved: every mapped value against its raw value,
        # row by row (POSITIONAL JOIN; CTAS keeps insertion order), plus the row count.
        for c in $ts_cols; do
            moved=$(query "select count(*) from thelook_ecommerce.\"${t}__raw\" r
                           positional join (select \"$c\" as m from thelook_ecommerce.\"$t\") n
                           where epoch_us(r.\"$c\") is distinct from epoch_us(n.m)")
            n_ts=$((n_ts + 1)); moved_total=$((moved_total + moved))
            if [ "$moved" != "0" ]; then
                printf 'FAIL  %s.%s: %s rows changed instant between the raw and the mapped copy\n' "$t" "$c" "$moved"
                failed=1
            fi
        done
        n_raw=$(query "select count(*) from thelook_ecommerce.\"${t}__raw\"")
        query "DROP TABLE thelook_ecommerce.\"${t}__raw\"" >/dev/null
        map_s=$(secs "$t1" "$(now)")
    fi

    n=$(query "select count(*) from thelook_ecommerce.\"$t\"")
    status=ok
    if [ "$n" != "${num_rows[$t]}" ] || { [ "$raw" -eq 0 ] && [ "$n" != "$n_raw" ]; }; then
        status=FAIL; failed=1
    fi
    printf '%-22s %10s %10s %6s %11s %10s %8s %6s\n' "$t" "$n" "${num_rows[$t]}" "$status" \
        "$(secs "$t0" "$t1")" "$map_s" "$n_ts" "$moved_total"
done
printf 'total wall %s s for %s tables\n' "$(secs "$started" "$(now)")" "${#TABLES[@]}"

# --------------------------------------------------------------- what landed
printf '\nColumns as loaded (table | column | DuckDB type):\n'
query "select table_name, column_name, data_type from information_schema.columns
       where table_catalog = current_database() and table_schema = 'thelook_ecommerce'
       order by table_name, ordinal_position" | sed 's/^/  /'

# The fixture's schema against the real one (D3): build the fixture into a scratch
# file and diff the column lists. Measured, so the report never has to assume it.
fx_dir=$(mktemp -d)
trap 'rm -rf "$fx_dir"' EXIT
if "$DUCKDB_BIN" -bail -init /dev/null "$fx_dir/fx.duckdb" < scripts/fixtures/thelook_ecommerce.sql >/dev/null 2>&1; then
    printf '\nReal vs fixture schema (columns that differ; the fixture is the local stand-in):\n'
    diff_rows=$(query "attach '$fx_dir/fx.duckdb' as fx (read_only);
        with r as (select table_name t, column_name c, data_type ty from information_schema.columns
                   where table_catalog = current_database() and table_schema = 'thelook_ecommerce'),
             f as (select table_name t, column_name c, data_type ty from information_schema.columns
                   where table_catalog = 'fx' and table_schema = 'thelook_ecommerce')
        select coalesce(r.t, f.t), coalesce(r.c, f.c),
               case when f.c is null then 'only in real' when r.c is null then 'only in fixture'
                    else 'type differs' end,
               coalesce(r.ty, '-'), coalesce(f.ty, '-')
        from r full join f on r.t = f.t and r.c = f.c
        where r.c is null or f.c is null or r.ty <> f.ty
        order by 1, 2")
    if [ -n "$diff_rows" ]; then
        printf '  %-22s %-26s %-16s %-28s %s\n' table column difference real fixture
        while IFS='|' read -r t c what rt ft; do
            printf '  %-22s %-26s %-16s %-28s %s\n' "$t" "$c" "$what" "$rt" "$ft"
        done <<< "$diff_rows"
    else
        printf '  none\n'
    fi
else
    printf '\nReal vs fixture schema: could not build the fixture into a scratch file (skipped)\n'
fi

# ----------------------------------------------------------------- the D2 probe
# What the DuckDB branch of to_utc_timestamp does to every timestamp column as loaded:
# timezone('UTC', cast(c as timestamptz)). A row is "shifted" when the instant it
# yields differs from the instant stored. 0 on the mapped load; on the raw load this
# is the measured size of the gap between the extension and the source contract.
probe() {
    local tz=$1 sql="" t c
    while IFS='|' read -r t c; do
        sql+="${sql:+ union all }select '$t', '$c', typeof(any_value(\"$c\")), count(\"$c\"),
              count(*) filter (where epoch_us(timezone('UTC', cast(\"$c\" as timestamptz))) <> epoch_us(\"$c\")),
              coalesce(list_sort(list(distinct (epoch_us(timezone('UTC', cast(\"$c\" as timestamptz))) - epoch_us(\"$c\")) / 3600000000.0)
                       filter (where \"$c\" is not null))::varchar, '[]'),
              min(\"$c\")::varchar, (timezone('UTC', cast(min(\"$c\") as timestamptz)))::varchar
              from thelook_ecommerce.\"$t\""
    done < <(query "select table_name, column_name from information_schema.columns
                    where table_catalog = current_database() and table_schema = 'thelook_ecommerce'
                      and data_type like 'TIMESTAMP%' order by table_name, ordinal_position")
    printf '\nD2 probe, session TimeZone %s (macro = timezone('"'"'UTC'"'"', cast(c as timestamptz))):\n' "$tz"
    printf '  %-22s %-14s %-26s %9s %9s  %-12s %-32s %s\n' table column type non_null shifted shift_h min_value macro_of_min
    query "set TimeZone = '$tz'; $sql" | while IFS='|' read -r t c ty nn sh hs mn mm; do
        printf '  %-22s %-14s %-26s %9s %9s  %-12s %-32s %s\n' "$t" "$c" "$ty" "$nn" "$sh" "$hs" "$mn" "$mm"
    done
}
probe "$(query "select current_setting('TimeZone')")"
if [ -n "${PROBE_TZ:-}" ]; then probe "$PROBE_TZ"; fi

if [ "$failed" -ne 0 ]; then
    printf '\nReal sources NOT loaded cleanly; see the FAIL lines above.\n'
    exit 1
fi
if [ "$raw" -eq 1 ]; then
    printf '\nReal sources loaded as the extension returns them (raw timestamps) into %s; every row count matches BigQuery.\n' "${DUCKDB_DB#"$repo_root"/}"
else
    printf '\nReal sources loaded into %s: every row count matches BigQuery, every timestamp mapped to TIMESTAMPTZ with no instant moved.\n' "${DUCKDB_DB#"$repo_root"/}"
fi
