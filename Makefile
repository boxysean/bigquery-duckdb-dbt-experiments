# One project, two targets: BigQuery and DuckDB.
#
# profiles.yml is committed next to the project, so nothing has to be copied into
# ~/.dbt for these targets to work — the Makefile points dbt at the repo copy.
SHELL := /bin/bash
.DEFAULT_GOAL := help

DBT := $(CURDIR)/.venv/bin/dbt
export DBT_PROFILES_DIR := $(CURDIR)

.PHONY: help setup check-env fixtures duck bq build-both parity polyglot portability transport-a clean

help:
	@printf 'make targets:\n\n'
	@printf '  make setup        install dbt v2 (uv sync) + the non-pip prerequisites:\n'
	@printf '                    dbc, the DuckDB ADBC driver, the DuckDB 1.5.x CLI, the\n'
	@printf '                    community bigquery extension\n'
	@printf '  make check-env    assert every prerequisite, failing loudly on any gap\n'
	@printf '  make fixtures     (re)load the thelook_ecommerce fixture into dev.duckdb\n'
	@printf '  make duck         fixtures, then dbt build --target duckdb (dev.duckdb)\n'
	@printf '  make bq           dbt build --target bigquery  (needs Google credentials;\n'
	@printf '                    refuses with exit 2 when the machine has none)\n'
	@printf '  make build-both   both targets, in that order\n'
	@printf '  make parity       compare every model across both targets: row count,\n'
	@printf '                    column names, canonical column types and a per-column\n'
	@printf '                    order-independent checksum; writes parity-report.md and\n'
	@printf '                    .json and exits non-zero on a real mismatch\n'
	@printf '  make polyglot     the macro layer end to end: self-check on DuckDB, renders\n'
	@printf '                    for both targets, the decimal ceiling, the guardrail\n'
	@printf '  make transport-a  Transport A measured: DuckDB reading BigQuery through the\n'
	@printf '                    community bigquery extension (INSTALL/LOAD, secret scope,\n'
	@printf '                    attach modes, pushdown, dry-run cost, parallelism, types).\n'
	@printf '                    Writes analyses/transport_a/results.{json,md} and logs/;\n'
	@printf '                    needs BQ_KEYFILE and Google credentials, and costs money.\n'
	@printf '  make portability  compile both targets and scan each render for the other\n'
	@printf '                    dialect (scripts/check_portability.py)\n'
	@printf '  make clean        remove target/ and the local dev.duckdb file\n\n'
	@printf 'See README.md, in particular the "What is verified" section.\n'

setup:
	uv sync
	bash scripts/install_prereqs.sh

check-env:
	bash scripts/check_env.sh

# The local stand-in for bigquery-public-data.thelook_ecommerce, recreated in
# dev.duckdb on every run. DuckDB only: the BigQuery target reads the real data.
fixtures:
	bash scripts/load_duckdb_sources.sh

# The duckdb target is the one that runs on a clean machine.
duck: check-env fixtures
	$(DBT) build --target duckdb

# Configured but not runnable without credentials; the script says so plainly.
bq: check-env
	bash scripts/run_bq.sh

build-both: duck bq

parity: check-env
	python3 scripts/parity.py

# The macro layer in one command (SPEC 7.4); the script re-runs both prerequisites
# itself so it also works on its own.
polyglot: check-env fixtures
	bash scripts/polyglot_check.sh

# The guardrail: no BigQuery-only token in the DuckDB render, no DuckDB-only token in
# the BigQuery render, no target branching in models/ or tests/. Needs dev.duckdb.
portability: check-env
	python3 scripts/check_portability.py

# Transport A measured (analyses/transport_a/README.md). Not part of `make duck`:
# it needs Google credentials AND it runs real BigQuery jobs, so it costs bytes.
# Export BQ_KEYFILE (the service-account key path) first; nothing is committed and
# the harness only passes the path to DuckDB.
transport-a:
	@python3 scripts/transport_a_measure.py

# `dbt clean` is deliberately not used: it resolves the duckdb profile first,
# which opens the very file it is asked to delete, and the failing exit that
# follows leaves target/ behind with the .duckdb file recreated.
clean:
	rm -rf target dbt_packages dbt_internal_packages
	rm -f dev.duckdb dev.duckdb.wal
