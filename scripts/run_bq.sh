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
#
set -uo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root" || exit 1

adc="$HOME/.config/gcloud/application_default_credentials.json"

if [ -f "$adc" ]; then
    printf '[bq] using gcloud application-default credentials at %s\n' "$adc"
elif [ -n "${GOOGLE_APPLICATION_CREDENTIALS:-}" ]; then
    printf '[bq] using the key file in GOOGLE_APPLICATION_CREDENTIALS=%s\n' "$GOOGLE_APPLICATION_CREDENTIALS"
    printf '[bq] NOTE: profiles.yml uses method: oauth. For a service-account key file,\n'
    printf '[bq]       set method: service-account and keyfile: <path> in the bigquery output.\n'
else
    cat <<'EOF'
[bq] BigQuery target is CONFIGURED but NOT RUNNABLE on this machine: no Google
[bq] credentials are present, and this repository does not ship any.
[bq]
[bq] The profile (profiles.yml > bigquery) points at GCP project
[bq] 'coreychimpbot', dataset 'experiments_<DBT_ENV>' (default experiments_dev),
[bq] location US, with maximum_bytes_billed as a hard cost ceiling. That
[bq] configuration has never been exercised against the real API.
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

exec "$repo_root/.venv/bin/dbt" build --target bigquery "$@"
