#!/usr/bin/env bash
#
# Start the local Spark endpoint the `spark` target connects to: a Spark 4.2.0
# Thrift Server (HiveServer2) on 127.0.0.1:10000, from the pip pyspark wheel on
# JDK 21 (both installed by scripts/install_prereqs.sh).
#
#   scripts/start_spark.sh
#
# If something already listens on the port, it says so and starts nothing: a
# second server would fight the first for the Derby metastore lock.
#
# The launch below reproduces, flag for flag, the server measured on this box on
# 2026-10-06 (read back from /proc/<pid>/cmdline):
#
#   JAVA_HOME=~/.local/spark/jdk SPARK_HOME=<venv>/site-packages/pyspark SPARK_LOCAL_IP=127.0.0.1 \
#   SPARK_SUBMIT_OPTS=-Dderby.connection.requireAuthentication=false \
#   spark-submit --master 'local[2]' --conf spark.driver.memory=2g \
#     --conf spark.sql.session.timeZone=UTC --conf spark.sql.catalogImplementation=hive \
#     --conf spark.sql.warehouse.dir=~/.local/spark/warehouse --conf spark.ui.enabled=false \
#     --conf spark.driver.extraJavaOptions=-Dderby.system.home=~/.local/spark/metastore_db \
#     --class org.apache.spark.sql.hive.thriftserver.HiveThriftServer2 --name SparkThriftServer \
#     spark-internal --hiveconf hive.server2.thrift.port=10000 \
#     --hiveconf hive.server2.thrift.bind.host=127.0.0.1
#
# Verified by diffing /proc/<pid>/cmdline of a scratch server (SPARK_PORT=10001,
# SPARK_STATE_DIR=/tmp/...) against the measured one: identical except that
# -Dderby.connection.requireAuthentication=false, passed here via SPARK_SUBMIT_OPTS,
# sits earlier on the java command line (where the original got it is not
# recoverable from /proc; the JVM property is the same either way).
#
# The session time zone is pinned to UTC: that is what makes a Spark TIMESTAMP the
# same instant-rendered-in-UTC as a BigQuery TIMESTAMP (macros/polyglot/casting.sql).
#
# Environment (defaults reproduce the server above; override to run a scratch one):
#   SPARK_PREFIX     ~/.local/spark
#   SPARK_PORT       10000
#   SPARK_STATE_DIR  $SPARK_PREFIX   (metastore_db/, warehouse/, thriftserver.{log,pid})
#   SPARK_WAIT_SECS  180             how long to wait for the port to open
#
set -uo pipefail

SPARK_PREFIX="${SPARK_PREFIX:-$HOME/.local/spark}"
SPARK_PORT="${SPARK_PORT:-10000}"
SPARK_STATE_DIR="${SPARK_STATE_DIR:-$SPARK_PREFIX}"
SPARK_WAIT_SECS="${SPARK_WAIT_SECS:-180}"
HOST=127.0.0.1

export JAVA_HOME="$SPARK_PREFIX/jdk"
VENV="$SPARK_PREFIX/venv"
PY="$VENV/bin/python"
METASTORE="$SPARK_STATE_DIR/metastore_db"
WAREHOUSE="$SPARK_STATE_DIR/warehouse"
LOG="$SPARK_STATE_DIR/thriftserver.log"
PIDFILE="$SPARK_STATE_DIR/thriftserver.pid"

listening() { (exec 3<>"/dev/tcp/$HOST/$SPARK_PORT") 2>/dev/null; }
listener_pid() { ss -ltnpH "sport = :$SPARK_PORT" 2>/dev/null | sed -n 's/.*pid=\([0-9]*\).*/\1/p' | head -n1; }

if listening; then
    printf '[spark] already running: %s:%s is listening (pid %s); not starting a second server\n' \
        "$HOST" "$SPARK_PORT" "$(listener_pid || true)"
    exit 0
fi

[ -x "$JAVA_HOME/bin/java" ] || { printf '[spark] FAIL no JDK at %s. Run scripts/install_prereqs.sh\n' "$JAVA_HOME"; exit 1; }
SPARK_HOME=$("$PY" -c 'import os, pyspark; print(os.path.dirname(pyspark.__file__))' 2>/dev/null) \
    || { printf '[spark] FAIL no pyspark in %s. Run scripts/install_prereqs.sh\n' "$VENV"; exit 1; }
export SPARK_HOME SPARK_LOCAL_IP="$HOST"
export SPARK_SUBMIT_OPTS="-Dderby.connection.requireAuthentication=false"
export PATH="$JAVA_HOME/bin:$PATH"

mkdir -p "$METASTORE" "$WAREHOUSE"
# Derby writes derby.log into the working directory; keep it beside the metastore.
cd "$SPARK_STATE_DIR" || exit 1

printf '[spark] starting Spark %s Thrift Server on %s:%s (log: %s)\n' \
    "$("$PY" -c 'import pyspark; print(pyspark.__version__)')" "$HOST" "$SPARK_PORT" "$LOG"
nohup "$VENV/bin/spark-submit" \
    --master 'local[2]' \
    --conf spark.driver.memory=2g \
    --conf spark.sql.session.timeZone=UTC \
    --conf spark.sql.catalogImplementation=hive \
    --conf "spark.sql.warehouse.dir=$WAREHOUSE" \
    --conf spark.ui.enabled=false \
    --conf "spark.driver.extraJavaOptions=-Dderby.system.home=$METASTORE" \
    --class org.apache.spark.sql.hive.thriftserver.HiveThriftServer2 \
    --name SparkThriftServer \
    spark-internal \
    --hiveconf "hive.server2.thrift.port=$SPARK_PORT" \
    --hiveconf "hive.server2.thrift.bind.host=$HOST" \
    > "$LOG" 2>&1 < /dev/null &
launcher=$!

for ((i = 0; i < SPARK_WAIT_SECS; i++)); do
    if listening; then
        pid=$(listener_pid || true)
        printf '%s\n' "${pid:-$launcher}" > "$PIDFILE"
        printf '[spark] up after %ss: %s:%s listening (pid %s)\n' "$i" "$HOST" "$SPARK_PORT" "${pid:-$launcher}"
        exit 0
    fi
    if ! kill -0 "$launcher" 2>/dev/null; then
        printf '[spark] FAIL the server exited before opening the port. Last lines of %s:\n' "$LOG"
        tail -n 20 "$LOG" | sed 's/^/    /'
        exit 1
    fi
    sleep 1
done
printf '[spark] FAIL port %s not open after %ss (pid %s still running; see %s)\n' \
    "$SPARK_PORT" "$SPARK_WAIT_SECS" "$launcher" "$LOG"
exit 1
