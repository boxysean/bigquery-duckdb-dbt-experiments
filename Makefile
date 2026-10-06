# One project, two targets: BigQuery and DuckDB.
#
# profiles.yml is committed next to the project, so nothing has to be copied into
# ~/.dbt for these targets to work — the Makefile points dbt at the repo copy.
SHELL := /bin/bash
.DEFAULT_GOAL := help

DBT := $(CURDIR)/.venv/bin/dbt
export DBT_PROFILES_DIR := $(CURDIR)

.PHONY: help setup check-env fixtures duck fixtures-real duck-real value-parity row-join bq build-both parity polyglot portability pre-pr ci-compile transport-a transport-b move-to-duckdb handmove-example clean

help:
	@printf 'make targets:\n\n'
	@printf '  make setup        install dbt v2 (uv sync) + the non-pip prerequisites:\n'
	@printf '                    dbc, the DuckDB ADBC driver, the DuckDB 1.5.x CLI, the\n'
	@printf '                    community bigquery extension\n'
	@printf '  make check-env    assert every prerequisite, failing loudly on any gap\n'
	@printf '  make fixtures     (re)load the thelook_ecommerce fixture into dev.duckdb\n'
	@printf '  make duck         fixtures, then dbt build --target duckdb (dev.duckdb)\n'
	@printf '  make fixtures-real  load the REAL bigquery-public-data.thelook_ecommerce\n'
	@printf '                    into dev.duckdb through the community bigquery extension\n'
	@printf '                    (all 7 tables, timestamps as TIMESTAMPTZ, row counts checked\n'
	@printf '                    against BigQuery). Needs BQ_KEYFILE; ~40 s; raw log in\n'
	@printf '                    analyses/value_parity/logs/loader.log\n'
	@printf '  make duck-real    fixtures-real, then dbt build --target duckdb\n'
	@printf '  make value-parity the value-equality run: fixtures-real, both builds, then\n'
	@printf '                    every model compared on the SAME input rows, rows and\n'
	@printf '                    checksums gating (parity.py --sources real --bq-source\n'
	@printf '                    materialised --same-data). Writes analyses/value_parity/\n'
	@printf '                    results.{md,json} and logs/; needs BQ_KEYFILE, costs money\n'
	@printf '  make row-join     after make value-parity with the same DBT_ENV (use\n'
	@printf '                    DBT_ENV=rows): join the two legs row by row on each model'"'"'s\n'
	@printf '                    key, every money column, with an L9 control build\n'
	@printf '                    (money_type() = decimal(38,9)) in target/row_join/. Gates:\n'
	@printf '                    source rows, row counts, transfer proof (exit 2 before the\n'
	@printf '                    join). Writes analyses/value_parity/rows.{md,json} and\n'
	@printf '                    logs/rows/; needs BQ_KEYFILE (Storage API + view queries)\n'
	@printf '  make bq           dbt build --target bigquery  (needs Google credentials;\n'
	@printf '                    refuses with exit 2 when the machine has none)\n'
	@printf '                    preflight first: creates a missing dataset, else exit 2 naming the grant\n'
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
	@printf '  make pre-pr       the whole pre-PR routine: check-env, the fixture, the\n'
	@printf '                    guardrail, then parity (scripts/pre_pr.sh). The script exits\n'
	@printf '                    1 on a real finding, 2 when parity is NOT established (no\n'
	@printf '                    BQ_KEYFILE; the guardrail still ran). make itself exits 2\n'
	@printf '                    on either and prints it as "Error 1" / "Error 2"\n'
	@printf '  make ci-compile   compile BOTH targets and run the guardrail — the same thing\n'
	@printf '                    CI runs on every push and PR (scripts/ci_compile_both.sh).\n'
	@printf '                    The script exits 1 on a real finding, 2 when the BigQuery\n'
	@printf '                    leg could not be established (no credential; the DuckDB\n'
	@printf '                    leg still ran)\n'
	@printf '  make transport-b  Transport B measured: EXPORT DATA to GCS as Parquet and\n'
	@printf '                    back through DuckDB (the wildcard/split and 1 GB rules, the\n'
	@printf '                    nested-to-CSV and JSON-to-Parquet refusals, row order, the\n'
	@printf '                    reverse load, and the type-fidelity table). Writes\n'
	@printf '                    analyses/transport_b/results.{json,md} and logs/; needs\n'
	@printf '                    BQ_KEYFILE, a writable GCS bucket, and costs money.\n'
	@printf '  make move-to-duckdb  move the project to a DuckDB-only one in\n'
	@printf '                    target/duckdb_only (seam macros inlined, source database,\n'
	@printf '                    profile and dbt_project rewritten), build it, and write\n'
	@printf '                    MOVE-REPORT.md (scripts/move_to_duckdb.py)\n'
	@printf '  make handmove-example  the worked example: move with three models left for\n'
	@printf '                    a hand move, drop in examples/duckdb_only/, prove each\n'
	@printf '                    equals the automatic transcode (diff -w) and build green\n'
	@printf '                    (target/handmove_example, target/handmove_example_auto)\n'
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

# The real dataset instead of the fixture (SPEC-value-parity.md, Transport A). Reads
# BigQuery tables through the Storage Read API (not query jobs); needs BQ_KEYFILE.
# `make fixtures` (or `make duck`, `make polyglot`, `make pre-pr`) puts the fixture back.
fixtures-real:
	bash scripts/load_duckdb_real_sources.sh

duck-real: check-env fixtures-real
	$(DBT) build --target duckdb

# Value equality end to end: both legs read the same rows, and parity.py builds both
# targets itself (so it can copy each run_results.json aside before the next build
# overwrites it), measures the materialised relations and gates on values. Every line
# it prints is also in analyses/value_parity/logs/parity.log. Exit 1 when a model's
# values differ: that is the finding, not a harness failure.
value-parity: check-env fixtures-real
	@set -o pipefail; python3 scripts/parity.py --sources real --bq-source materialised \
	    --same-data --out-dir analyses/value_parity 2>&1 | tee analyses/value_parity/logs/parity.log

# Row-by-row join of the pair value-parity last built (SPEC-rows.md). Refuses
# DBT_ENV=dev: experiments_dev is the of-record leg, whose source has since moved.
row-join: check-env
	python3 scripts/row_join.py

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

# Everything to run before a PR (scripts/pre_pr.sh). No prerequisites on purpose: the
# script runs check-env itself, and parity.py already runs `make duck`. GNU make exits 2
# for any failed recipe, so the script's 1-vs-2 survives only as make's "Error N" line;
# call `bash scripts/pre_pr.sh` directly when the exit status itself matters.
pre-pr:
	bash scripts/pre_pr.sh

# Both targets compiled, plus the guardrail (scripts/ci_compile_both.sh): the one
# command CI runs (.github/workflows/ci.yml), and the one to run locally before a PR.
# No prerequisites on purpose: the script runs check-env and the fixture itself. GNU
# make reports the script's exit 2 (BigQuery leg not established) as "Error 2", and its
# exit 1 as "Error 1", but make itself exits 2 for both; call
# `bash scripts/ci_compile_both.sh` directly when the exit status itself matters.
ci-compile:
	bash scripts/ci_compile_both.sh

# Transport A measured (analyses/transport_a/README.md). Not part of `make duck`:
# it needs Google credentials AND it runs real BigQuery jobs, so it costs bytes.
# Export BQ_KEYFILE (the service-account key path) first; nothing is committed and
# the harness only passes the path to DuckDB.
transport-a:
	@python3 scripts/transport_a_measure.py

# Transport B measured (analyses/transport_b/README.md): EXPORT DATA to GCS as Parquet,
# read back through DuckDB over the GCS XML API, and the reverse load. Costs BigQuery
# bytes and writes objects into the bucket; b31 deletes every object it wrote and drops
# the probe tables, so the bucket and the dataset are left as they were found.
transport-b:
	@python3 scripts/transport_b_measure.py

# The code-movement procedure: this BigQuery-targeted project -> a DuckDB-only one
# (docs/move_to_duckdb.md). jinja2 comes from the dev group of `uv sync`.
PYTHON := $(CURDIR)/.venv/bin/python
move-to-duckdb:
	$(PYTHON) scripts/move_to_duckdb.py --out target/duckdb_only --force --verify

# The worked example: the three models in examples/duckdb_only/ were moved by hand.
# Move the project leaving them as HAND-MOVE placeholders (exit 3), drop the hand-moved
# files in, require each to equal the automatic transcode ignoring whitespace and the
# `-- [hand-moved]` header lines, then require a green build.
HANDMOVE_MODELS := models/staging/stg_thelook__orders.sql models/marts/dim_date.sql models/marts/mart_daily_revenue.sql
HM := $(CURDIR)/target/handmove_example
handmove-example:
	@set -uo pipefail; \
	$(PYTHON) scripts/move_to_duckdb.py --out $(HM)_auto --force > $(HM)_auto.log 2>&1 \
	    || { echo "handmove-example: FAIL automatic move exited $$? (see $(HM)_auto.log)"; exit 1; }; \
	$(PYTHON) scripts/move_to_duckdb.py --out $(HM) --force \
	    --manual dim_date,stg_thelook__orders,mart_daily_revenue > $(HM).log 2>&1; rc=$$?; \
	[ $$rc -eq 3 ] || { echo "handmove-example: FAIL --manual exited $$rc, expected 3 (see $(HM).log)"; exit 1; }; \
	for f in $(HANDMOVE_MODELS); do \
	    cp examples/duckdb_only/$$f $(HM)/$$f; \
	    if ! diff -w -I '^-- \[hand-moved\]' $(HM)/$$f $(HM)_auto/$$f; then \
	        echo "handmove-example: FAIL $$f differs from the automatic transcode"; exit 1; fi; \
	done; \
	(cd $(HM) && DBT_PROFILES_DIR=$(HM) $(DBT) build --target duckdb) > $(HM)/build.log 2>&1; rc=$$?; \
	summary=$$(grep -E '^Summary:' $(HM)/build.log); processed=$$(grep -E '^Processed:' $(HM)/build.log); \
	if [ $$rc -ne 0 ] || ! [[ "$$summary" =~ ^Summary:\ ([0-9]+)\ total\ \|\ ([0-9]+)\ success$$ ]] \
	    || [ "$${BASH_REMATCH[1]}" != "$${BASH_REMATCH[2]}" ]; then \
	    echo "handmove-example: FAIL build exit $$rc: $$processed / $$summary (see $(HM)/build.log)"; exit 1; fi; \
	echo "handmove-example: 3/3 hand-moved models equal the automatic transcode (diff -w); build green: $$processed | $$summary"

# `dbt clean` is deliberately not used: it resolves the duckdb profile first,
# which opens the very file it is asked to delete, and the failing exit that
# follows leaves target/ behind with the .duckdb file recreated.
clean:
	rm -rf target dbt_packages dbt_internal_packages
	rm -f dev.duckdb dev.duckdb.wal
