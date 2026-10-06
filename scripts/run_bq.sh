#!/usr/bin/env bash
#
# The BigQuery leg.
#
# This repository does not hold Google credentials, and it must not pretend it
# does. Without them `dbt build --target bigquery` ends in an authentication
# error from the driver; this wrapper replaces that with a sentence that says
# what is actually wrong and what to do about it, and exits 2 (distinct from the
# exit 1 of a real build failure) so `make build-both` can be read at a glance.
#
#   scripts/run_bq.sh            # extra args are passed through to dbt build
#   BQ_NO_PREFLIGHT=1 scripts/run_bq.sh   # skip the preflight below
#
# Credentials: the profile reads BQ_KEYFILE (a service-account key file, with
# method: service-account) or falls back to gcloud application-default
# credentials. With those, this is the whole BigQuery leg, and it runs for real:
# measured 2026-09-27 (card t_d87cf14b) and again 2026-10-06 (card t_fc6d405f),
# 29 models built, 195 of 196 tests passing plus one intended warning. Earlier
# cards (t_52340fa8, t_d0cac5da) ran before the service account's grants
# landed, when every model failed with "Dataset ... was not found"; that is
# history, not the current state.
#
# What the wrapper promises now: a target it cannot write says WHAT TO GRANT
# instead of relaying a driver error. With a service-account key file in play
# (BQ_KEYFILE, or GOOGLE_APPLICATION_CREDENTIALS), it first runs
# `scripts/bq_preflight.py --create`, which creates the target dataset if it is
# missing (and nothing else) and checks that a job can be created and the
# dataset read. Its exit 2 (named blocker: the permission and the two `gcloud`
# grants have been printed) is this script's exit 2, and no build starts. Its
# exit 1 (preflight unavailable: no openssl, network, ...) says nothing about
# the target, so the build goes ahead as before. gcloud ADC is not covered by
# the preflight. Without a writable dataset, scripts/parity.py can still
# measure the same models read-only.
#
set -uo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root" || exit 1

adc="$HOME/.config/gcloud/application_default_credentials.json"

if [ -f "$adc" ]; then
    printf '[bq] using gcloud application-default credentials at %s\n' "$adc"
elif [ -n "${GOOGLE_APPLICATION_CREDENTIALS:-}" ]; then
    printf '[bq] using the key file in GOOGLE_APPLICATION_CREDENTIALS=%s\n' "$GOOGLE_APPLICATION_CREDENTIALS"
    printf '[bq] NOTE: profiles.yml uses method: oauth by default. For a service-account key file,\n'
    printf '[bq]       export BQ_KEYFILE=<path> instead (the profile reads it, with\n'
    printf '[bq]       BQ_AUTH_METHOD=service-account).\n'
elif [ -n "${BQ_KEYFILE:-}" ]; then
    # The profile reads this variable itself (profiles.yml > bigquery > keyfile),
    # so nothing has to be copied: method becomes service-account, keyfile the path.
    export BQ_AUTH_METHOD="${BQ_AUTH_METHOD:-service-account}"
    printf '[bq] using the service-account key file in BQ_KEYFILE=%s (method=%s)\n' \
        "$BQ_KEYFILE" "$BQ_AUTH_METHOD"
else
    cat <<'EOF'
[bq] BigQuery target is CONFIGURED but NOT RUNNABLE on this machine: no Google
[bq] credentials are present, and this repository does not ship any.
[bq]
[bq] The profile (profiles.yml > bigquery) points at GCP project
[bq] 'coreychimpbot', dataset 'experiments_<DBT_ENV>' (default experiments_dev),
[bq] location US, with maximum_bytes_billed as a hard cost ceiling. That
[bq] configuration has been exercised against the real API since 2026-09-27;
[bq] this machine just has no credentials for it.
[bq]
[bq] To make this leg real, pick one:
[bq]   gcloud auth application-default login \
[bq]     --scopes=https://www.googleapis.com/auth/bigquery,https://www.googleapis.com/auth/cloud-platform
[bq]   # or a service account key file, with method: service-account + keyfile: in profiles.yml
[bq]
[bq] Nothing was run. DuckDB parity work does not depend on this.
EOF
    exit 2
fi

# The preflight covers service-account key files only; the ADC branch above wins
# over a key file, exactly as the profile's auth method does.
if [ -n "${BQ_NO_PREFLIGHT:-}" ] && [ "${BQ_NO_PREFLIGHT}" != 0 ]; then
    printf '[bq] BQ_NO_PREFLIGHT=%s: skipping scripts/bq_preflight.py\n' "$BQ_NO_PREFLIGHT"
elif [ -f "$adc" ]; then
    printf '[bq] preflight skipped: it covers service-account keys only, not gcloud ADC\n'
else
    python3 "$repo_root/scripts/bq_preflight.py" --create
    rc=$?
    if [ "$rc" -eq 2 ]; then
        printf '[bq] preflight named a blocker (exit 2): no build was started.\n'
        exit 2
    elif [ "$rc" -ne 0 ]; then
        printf '[bq] preflight unavailable (exit %s); building anyway, as before the preflight existed\n' "$rc"
    fi
fi

exec "$repo_root/.venv/bin/dbt" build --target bigquery "$@"
