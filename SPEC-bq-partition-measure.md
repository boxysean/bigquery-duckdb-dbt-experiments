# Card t_55f119de, phase 2 — the measurement harness for the partitioning change

## Context

Phase 1 (already done and verified, do not touch it) added `macros/polyglot/physical.sql`
(`physical_layout()`) and applied it to `models/marts/fct_inventory_items.sql`, so on BigQuery that
mart is now a day-partitioned (`created_at`), `product_id`-clustered table while DuckDB keeps a plain
table. The protocol is written up in `analyses/partitioning/README.md`.

This phase adds the harness that measures the change on BigQuery and the Makefile target that exposes
it. The numbers themselves are produced by the orchestrator afterwards, from real jobs.

## Work

### 1. `scripts/bq_partition_measure.py` (new, stdlib only)

Same shape and register as this repository's other BigQuery scripts (`scripts/bq_table_meta.py`,
`scripts/bq_preflight.py`): a module docstring saying what it reads, what it costs and how to run it;
`from __future__ import annotations`; the access token from `scripts/parity.py`'s `access_token()`
loaded with `importlib` — copy `bq_table_meta.py`'s `_access_token` helper verbatim, it is the one
implementation of the JWT exchange here. Key from `BQ_KEYFILE` (required, never printed); project
from `BQ_PROJECT` (default `coreychimpbot`); ceiling from `BQ_MAXIMUM_BYTES_BILLED` (default
`1000000000`, the same 1 GB the profile carries — the card requires it stays in place).

Two subcommands:

    python3 scripts/bq_partition_measure.py measure --table PROJECT.DATASET.TABLE \
        --label before|after --window YYYY-MM [--out-dir analyses/partitioning]
    python3 scripts/bq_partition_measure.py report --before FILE --after FILE [--out-dir ...]

**`measure`** does three things; it prints everything as it goes and also writes
`<out-dir>/logs/<label>.log` (the same text) and `<out-dir>/results.<label>.json` (the structured
form):

1. **Table metadata**, from the REST `tables.get` endpoint (metadata read; bills nothing, cannot
   hit the ceiling): `numRows`, `numBytes`, `timePartitioning` (type, field, expirationMs) and
   `clustering.fields`. Print `none` for either when the table has it, rather than omitting the line:
   the presence of the partition and cluster columns is itself one of the card's acceptance criteria.
   Also print the table's `creationTime` and `lastModifiedTime`.
2. **Four query jobs**, each submitted with `jobs.insert` (`JobConfigurationQuery`) and read back
   with `jobs.get`, so every number comes from the jobs API:
   * `dry_run` — the representative query with `dryRun: true`. Free (BigQuery validates and returns
     `statistics.query.totalBytesProcessed` as an estimate, billing nothing); it is the cross-check
     the README promises.
   * `full_scan` — `SELECT * FROM <table>`: the whole-table cost, context for the next one.
   * `filtered_scan` — `SELECT * FROM <table> WHERE created_at >= TIMESTAMP '<first instant of the
     window>' AND created_at < TIMESTAMP '<first instant of the next month>'`: **the representative
     filtered query** the card asks for, of the shape an analyst runs against an inventory fact.
   * `filtered_count` — `SELECT COUNT(*) FROM <table>` with the same filter: the control that shows
     BigQuery's 10 MB per-query minimum billed flooring the answer.
   Each executed body carries `useQueryCache: false` (a cache hit bills 0 and would hide the change)
   and `maximumBytesBilled` set to the ceiling above. Record from `statistics.query`:
   `totalBytesProcessed`, `totalBytesBilled`, `cacheHit`, `statementType`, `schema` field count, and
   from `statistics`: `creationTime`, `endTime`, `totalSlotMs`. Record the `jobId` too so any number
   can be looked up again. **A query is not real unless `cacheHit` is recorded**: if a job reports
   `cacheHit: true`, say so loudly and treat the run as unusable (exit 1) rather than reporting a
   zero.
   A job refused with `bytesBilledLimitExceeded` is a **result, not a crash**: print BigQuery's own
   message, record the query as refused, and carry on with the rest.
3. **Rows per partition**, from `INFORMATION_SCHEMA.PARTITIONS` of the table's own dataset:
   `SELECT partition_id, total_rows, total_logical_bytes, total_billable_bytes FROM
   \`PROJECT.DATASET.INFORMATION_SCHEMA.PARTITIONS\` WHERE table_name = '<table>' ORDER BY
   partition_id`. Print the partition count, the first and last `partition_id`, the `__UNPARTITIONED__`
   row when present and its row count, the row count of the window's own partition, and the rows
   summed over real partitions. Keep the whole list in the JSON. On an unpartitioned table this query
   returns a single `__UNPARTITIONED__` row: that is a valid answer, not an error.

**`report`** reads the two JSONs and writes `<out-dir>/results.md` and prints it: the table metadata
before/after, one table per measured query (bytes processed and bytes billed for before and after,
absolute and percentage delta, and a one-line reading), and the partition summary. It must **exit 1
with a clear message if the two files are not the `before` and `after` of the same `--table`**, or if
either is missing, or if either run recorded a cache hit: a comparison across two different tables
would be a fabricated result.

Exit codes: `0` everything ran; `1` a job failed, a refused query, a cache hit, or a report that
cannot be honestly produced; `2` could not start (no `BQ_KEYFILE`, bad key, network).

### 2. `Makefile`

One new target, in the existing style, with a `help:` line in the same voice as its neighbours (it
runs one leg of the partitioning measurement, needs `BQ_KEYFILE`, runs real BigQuery jobs and costs
bytes, and refers to `analyses/partitioning/README.md`):

    partition-measure:
    	@python3 scripts/bq_partition_measure.py $(ARGS)

Add it to `.PHONY` and to the `help:` list (keep the file's existing ordering: `partition-measure`
next to the other measurement targets).

### 3. `analyses/partitioning/README.md`

Update the "What will be measured" section so it describes exactly what the harness does now: the
three executed queries plus the dry run, the `YYYY-MM` window, `useQueryCache: false`, the ceiling,
and the fact that `report` compares a `before` and an `after` run of the same table. Replace the
sentence promising "a few weeks and one `product_id`, aggregating a cost column" — the measured
query is a whole calendar month on `created_at`, selecting every column, because the point is what
partition pruning does to a scan that would otherwise read the whole table. Add a short "How to run
it" section with the exact command sequence, as plain shell lines:

  1. build the before leg: a scratch copy of this tree under `target/partition_before/` with the
     model's `physical_layout()` config line removed, built into the same dataset
     (`DBT_ENV=partition`, `--select +fct_inventory_items`, `dbt run`);
  2. `measure --label before`;
  3. build the after leg: the real tree, `DBT_ENV=partition make bq`;
  4. `measure --label after`;
  5. `report`.

Keep the file free of Jinja delimiters (`{{`, `{%`): dbt parses `.md` under `analyses/` as an
analysis and warns (`MacroSyntaxInvalid (dbt1502)`).

### 4. `macros/polyglot/self_check.sql`

Add one line to the `renders` list in `polyglot_render()` so the new macro is covered by
`make polyglot` like every other entry:

    ['physical_layout', physical_layout()],

Place it after `['type_bigint_array', ...]`. Do not add it to `polyglot_selfcheck()`: on DuckDB it
returns a dict, and that macro compares values as rendered text.

## Constraints

* No Jinja delimiters in anything under `analyses/`; never print or log the key or a token; never run
  a billable job from a test; do not add a `.sql` file under `analyses/`.
* Do not touch `macros/polyglot/physical.sql`, `models/`, `profiles.yml` or anything phase 1 wrote
  except the two edits above.

## Verify — run these and report the real output

* `python3 -m py_compile scripts/bq_partition_measure.py`.
* `python3 scripts/bq_partition_measure.py --help`, and the `--help` of `measure` and `report`.
* The no-credential path must exit 2 with a sentence, not a traceback:
  `env -u BQ_KEYFILE python3 scripts/bq_partition_measure.py measure --table coreychimpbot.experiments_partition.fct_inventory_items --label before --window 2022-01`
* `make -n partition-measure ARGS="--help"` shows the command make would run.
* `.venv/bin/dbt run-operation polyglot_render --target duckdb` and `--target bigquery` both exit 0
  and each prints a `render physical_layout <target> :: ...` line.
* `python3 scripts/check_portability.py` still prints `PORTABLE` with 0 findings.
* `git status --short`, `git diff --stat`, and the full diff of the files you changed.

The `.md` warning from `analyses/value_parity/rows.md` is pre-existing; do not "fix" it.
