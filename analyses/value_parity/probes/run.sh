#!/usr/bin/env bash
# Run one probe, raw output into analyses/value_parity/logs/probe_<name>.log.
#
#   bash analyses/value_parity/probes/run.sh decimal_text
set -o pipefail
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
name=${1:?usage: run.sh <probe name, e.g. decimal_text>}
log="$here/../logs/probe_$name.log"
{ echo "\$ python3 analyses/value_parity/probes/$name.py"; date -u +%Y-%m-%dT%H:%M:%SZ; } > "$log"
python3 "$here/$name.py" 2>&1 | tee -a "$log"
rc=$?
echo "# exit $rc" | tee -a "$log"
exit $rc
