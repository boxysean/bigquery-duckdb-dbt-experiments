# One project, two targets: BigQuery and Trino (an Iceberg lakehouse shared with Spark).
#
# dbt v1 (dbt-core) in this folder's own .venv (`make setup`). profiles.yml is committed
# next to the project; the Makefile points dbt at it.
SHELL := /bin/bash
.DEFAULT_GOAL := help

DBT := $(CURDIR)/.venv/bin/dbt
PY := $(CURDIR)/.venv/bin/python
COMPOSE := docker compose -f $(CURDIR)/stack/compose.yml
export DBT_PROFILES_DIR := $(CURDIR)

.PHONY: help setup jars check-env stack-up stack-down stack-reset fixture land-sources real-sources land-real trino trino-real bq parity rows selfcheck render portability portability-demo interop trees pre-pr clean

help:
	@printf 'make targets:\n\n'
	@printf '  make setup          uv sync (dbt-core, dbt-trino, dbt-bigquery, duckdb, trino client) + jars\n'
	@printf '  make jars           download the Spark Iceberg jars into stack/spark/jars (sha256-checked)\n'
	@printf '  make check-env      assert every prerequisite, failing loudly on any gap\n'
	@printf '  make stack-up       start the lakehouse: SeaweedFS (S3), Iceberg REST catalog, Trino\n'
	@printf '  make stack-down     stop it (data kept);  make stack-reset: stop and DELETE its volumes\n'
	@printf '  make fixture        render project 1'"'"'s fixture SQL to Parquet (the shared source rows)\n'
	@printf '  make land-sources   fixture, then the Spark job that lands lake.thelook_ecommerce.*\n'
	@printf '  make trino          land-sources, then dbt build --target trino\n'
	@printf '  make bq             dbt build --target bigquery (needs BQ_KEYFILE or ADC; costs money)\n'
	@printf '  make real-sources   download the REAL thelook tables from BigQuery to Parquet (free: no query)\n'
	@printf '  make land-real      real-sources, then Spark lands them as lake.thelook_ecommerce.*\n'
	@printf '  make trino-real     land-real, then dbt build --target trino on the real rows\n'
	@printf '  make parity         BigQuery vs Trino, every relation, every column (needs bq + trino-real)\n'
	@printf '  make rows           BigQuery vs Trino, row by row on each key: values and representations\n'
	@printf '  make selfcheck      execute every polyglot macro on Trino and check its value\n'
	@printf '  make render         log every macro'"'"'s rendering on both targets\n'
	@printf '  make portability    compile both targets, scan each render for the other dialect\n'
	@printf '  make portability-demo  prove the guardrail fails on a planted leak, then passes\n'
	@printf '  make interop        Spark reads every relation dbt built; profiles compared\n'
	@printf '  make trees          the two projects still build the same models (repo-level check)\n'
	@printf '  make pre-pr         everything CI runs, in one command (scripts/pre_pr.sh)\n'
	@printf '  make clean          remove target/ and dbt_packages/\n\n'

setup:
	uv sync --frozen
	bash scripts/fetch_spark_jars.sh

jars:
	bash scripts/fetch_spark_jars.sh

check-env:
	bash scripts/check_env.sh

stack-up:
	mkdir -p target/stack_io
	$(COMPOSE) up -d --wait

stack-down:
	$(COMPOSE) down

stack-reset:
	$(COMPOSE) down -v

fixture:
	$(PY) scripts/render_fixture.py

land-sources: fixture
	$(COMPOSE) run --rm spark land_sources.py

trino: land-sources
	$(DBT) build --target trino

bq:
	$(DBT) build --target bigquery

real-sources:
	$(PY) scripts/render_real.py

land-real: real-sources
	$(COMPOSE) run --rm -e SOURCE_DIR=/data/real spark land_sources.py

trino-real: land-real
	$(DBT) build --target trino

parity:
	$(PY) scripts/bq_trino_parity.py

rows:
	$(PY) scripts/bq_trino_rows.py

selfcheck:
	$(DBT) run-operation polyglot_selfcheck --target trino

render:
	$(DBT) run-operation polyglot_render --target trino
	@echo "(bigquery renders: make portability compiles it credential-free; see target/portability/bigquery)"

portability:
	$(PY) scripts/check_portability.py

portability-demo:
	$(PY) scripts/check_portability.py --demo

interop:
	$(PY) scripts/spark_interop.py

trees:
	$(PY) ../scripts/check_model_trees.py

pre-pr:
	bash scripts/pre_pr.sh

clean:
	rm -rf target dbt_packages logs
