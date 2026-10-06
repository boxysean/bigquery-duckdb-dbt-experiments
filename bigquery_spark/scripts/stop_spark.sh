#!/usr/bin/env bash
#
# Stop the local Spark Thrift Server started by scripts/start_spark.sh.
#
#   scripts/stop_spark.sh
#
# It stops whatever listens on SPARK_PORT, but only if that process really is a
# Spark HiveThriftServer2 — anything else on the port is reported and left alone.
# The metastore and warehouse are kept; the loaded thelook_ecommerce tables are
# still registered at the next start.
#
# Environment: SPARK_PREFIX, SPARK_PORT, SPARK_STATE_DIR as in start_spark.sh.
#
set -uo pipefail

SPARK_PREFIX="${SPARK_PREFIX:-$HOME/.local/spark}"
SPARK_PORT="${SPARK_PORT:-10000}"
SPARK_STATE_DIR="${SPARK_STATE_DIR:-$SPARK_PREFIX}"
HOST=127.0.0.1
PIDFILE="$SPARK_STATE_DIR/thriftserver.pid"

listening() { (exec 3<>"/dev/tcp/$HOST/$SPARK_PORT") 2>/dev/null; }

if ! listening; then
    printf '[spark] not running: nothing listens on %s:%s\n' "$HOST" "$SPARK_PORT"
    rm -f "$PIDFILE"
    exit 0
fi

pid=$(ss -ltnpH "sport = :$SPARK_PORT" 2>/dev/null | sed -n 's/.*pid=\([0-9]*\).*/\1/p' | head -n1)
if [ -z "$pid" ]; then
    printf '[spark] FAIL %s:%s is listening but its pid is not visible to this user\n' "$HOST" "$SPARK_PORT"
    exit 1
fi
if ! tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q 'HiveThriftServer2'; then
    printf '[spark] FAIL pid %s on port %s is not a Spark Thrift Server; leaving it alone\n' "$pid" "$SPARK_PORT"
    exit 1
fi

printf '[spark] stopping Spark Thrift Server pid %s on %s:%s\n' "$pid" "$HOST" "$SPARK_PORT"
kill "$pid"
for _ in $(seq 1 60); do
    if ! kill -0 "$pid" 2>/dev/null; then
        rm -f "$PIDFILE"
        printf '[spark] stopped\n'
        exit 0
    fi
    sleep 1
done
printf '[spark] FAIL pid %s still running 60s after SIGTERM\n' "$pid"
exit 1
