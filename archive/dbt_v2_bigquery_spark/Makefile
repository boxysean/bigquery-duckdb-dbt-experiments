# One project, two targets: BigQuery and Spark.
#
# profiles.yml is committed next to the project, so nothing has to be copied into
# ~/.dbt for these targets to work — the Makefile points dbt at this directory.
# dbt itself is the root project's (`uv sync` in the repository root).
SHELL := /bin/bash
.DEFAULT_GOAL := help

DBT := $(CURDIR)/../../1_dbt_bigquery_duckdb/.venv/bin/dbt
export DBT_PROFILES_DIR := $(CURDIR)
# Measured: dbt-oss 2.0.5 refuses the spark adapter without this (InvalidConfig dbt1005).
export DBT_ALLOW_EXPERIMENTAL_ADAPTERS := true
# The service-account key on this box, used when BQ_KEYFILE is not already set and
# the file exists. Nothing secret is committed: this is a path outside the repo.
export BQ_KEYFILE ?= $(wildcard $(HOME)/.config/gcp/coreychimpbot-sa.json)

# Selects the BigQuery auth method profiles.yml reads, or refuses with exit 2.
BQ_CREDENTIAL := \
	if [ -n "$$BQ_KEYFILE" ] && [ -f "$$BQ_KEYFILE" ]; then \
	    export BQ_AUTH_METHOD=$${BQ_AUTH_METHOD:-service-account}; \
	    echo "[bq] using the service-account key file in BQ_KEYFILE (method=$$BQ_AUTH_METHOD)"; \
	elif [ -n "$${GOOGLE_APPLICATION_CREDENTIALS:-}" ] || [ -f "$$HOME/.config/gcloud/application_default_credentials.json" ]; then \
	    echo "[bq] using application-default credentials (method=oauth)"; \
	else \
	    echo "[bq] BigQuery target is CONFIGURED but NOT RUNNABLE here: no credential (no BQ_KEYFILE,"; \
	    echo "[bq] no GOOGLE_APPLICATION_CREDENTIALS, no gcloud ADC). Nothing was run. The Spark leg"; \
	    echo "[bq] (make spark) does not depend on this once the sources are loaded."; \
	    exit 2; \
	fi

.PHONY: help setup check-env start-spark stop-spark load-sources spark bq portability parity value-parity polyglot pre-pr clean

help:
	@printf 'make targets:\n\n'
	@printf '  make setup        install the Spark prerequisites under ~/.local/spark (JDK 21,\n'
	@printf '                    pyspark 4.2.0, the BigQuery client for the loader); no sudo.\n'
	@printf '                    dbt itself is the root project'"'"'s: uv sync in the repo root\n'
	@printf '  make check-env    assert every prerequisite for both targets, failing loudly on\n'
	@printf '                    any gap; the BigQuery credential is reported, not required\n'
	@printf '  make start-spark  start the Spark 4.2.0 Thrift Server on 127.0.0.1:10000 (UTC\n'
	@printf '                    session); says "already running" if the port is taken\n'
	@printf '  make stop-spark   stop it (only if the listener really is a Spark Thrift Server)\n'
	@printf '  make load-sources pull the seven REAL bigquery-public-data.thelook_ecommerce tables\n'
	@printf '                    (table reads, no query job) to target/spark_sources/ as Parquet\n'
	@printf '                    and register them as thelook_ecommerce.<table> in Spark. Row\n'
	@printf '                    counts gated against BigQuery numRows, instants proved unmoved.\n'
	@printf '                    Needs a BigQuery credential; events (~2.4M rows) takes minutes.\n'
	@printf '                    TABLES=a,b loads a subset. Log: target/spark_sources/*.log\n'
	@printf '  make spark        start-spark, load-sources, then dbt build --target spark\n'
	@printf '  make bq           dbt build --target bigquery (needs a credential: BQ_KEYFILE,\n'
	@printf '                    default ~/.config/gcp/coreychimpbot-sa.json, or ADC; refuses\n'
	@printf '                    with exit 2 when the machine has none)\n'
	@printf '  make portability  compile both targets and scan each render for the other\n'
	@printf '                    dialect, plus target branching (scripts/check_portability.py)\n'
	@printf '  make parity       compare every model across both targets: row count, column\n'
	@printf '                    names, canonical types, per-column checksums (scripts/parity.py);\n'
	@printf '                    writes parity-report.md and .json\n'
	@printf '  make value-parity load-sources, then parity on the SAME real rows (--same-data);\n'
	@printf '                    needs a BigQuery credential, costs BigQuery bytes\n'
	@printf '  make polyglot     the macro layer end to end: self-check executed on Spark (and on\n'
	@printf '                    BigQuery when a credential is present), renders for both\n'
	@printf '                    targets, the Spark decimal ceiling failing by design, the guardrail\n'
	@printf '  make pre-pr       check-env + guardrail + parity (scripts/pre_pr.sh). The script\n'
	@printf '                    exits 1 on a real finding, 2 when a leg could not be measured;\n'
	@printf '                    make itself exits 2 on either and prints it as "Error 1" / "Error 2"\n'
	@printf '  make clean        remove target/ (INCLUDING the Parquet the Spark tables point at:\n'
	@printf '                    run make load-sources again afterwards)\n\n'
	@printf 'See README.md, SPEC.md and NOTES.md.\n'

setup:
	bash scripts/install_prereqs.sh

check-env:
	bash scripts/check_env.sh

start-spark:
	bash scripts/start_spark.sh

stop-spark:
	bash scripts/stop_spark.sh

# The loader exits 2 when there is no BigQuery credential, 1 on a row-count mismatch
# or a moved instant.
load-sources: start-spark
	python3 scripts/load_spark_sources.py $(if $(TABLES),--tables $(TABLES))

# The Spark leg end to end. check-env runs after start-spark: it requires the endpoint.
spark: start-spark check-env load-sources
	$(DBT) build --target spark

bq:
	@$(BQ_CREDENTIAL); \
	$(DBT) build --target bigquery

# Compiling the spark target needs the endpoint; nothing is built.
portability: start-spark
	python3 scripts/check_portability.py

parity: start-spark check-env
	python3 scripts/parity.py

value-parity: start-spark check-env load-sources
	@set -o pipefail; mkdir -p target; python3 scripts/parity.py --same-data 2>&1 | tee target/value_parity.log

# The decimal-ceiling step must FAIL: Spark DECIMAL caps at precision 38 and
# decimal_type(p > 38) raises a compiler error there instead of rendering double.
polyglot: start-spark check-env
	$(DBT) run-operation polyglot_selfcheck --target spark
	$(DBT) run-operation polyglot_render --target spark > target/polyglot_render_spark.txt
	$(DBT) run-operation polyglot_render --target bigquery > target/polyglot_render_bigquery.txt
	@if $(DBT) run-operation polyglot_render --args '{include_bignumeric: true}' --target spark \
	        > target/polyglot_decimal_ceiling.txt 2>&1; then \
	    echo "polyglot: FAIL the p > 38 decimal rendered on Spark; it must raise"; exit 1; \
	else \
	    echo "polyglot: the Spark decimal ceiling failed as designed:"; \
	    grep -m1 -i 'decimal' target/polyglot_decimal_ceiling.txt | cut -c1-240; \
	fi
	@if ( $(BQ_CREDENTIAL) ) > /dev/null; then \
	    $(BQ_CREDENTIAL); $(DBT) run-operation polyglot_selfcheck --target bigquery; \
	else \
	    echo "polyglot: BigQuery self-check SKIPPED (no credential)"; \
	fi
	python3 scripts/check_portability.py

# No prerequisites on purpose: the script runs check-env itself. GNU make exits 2 for
# any failed recipe; call `bash scripts/pre_pr.sh` directly when 1-vs-2 matters.
pre-pr:
	bash scripts/pre_pr.sh

clean:
	rm -rf target dbt_packages dbt_internal_packages
