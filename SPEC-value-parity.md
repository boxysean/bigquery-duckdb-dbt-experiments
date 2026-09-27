# SPEC — value equality: one real dataset, both targets, every mart compared

You are implementing card `t_d92586d6` in this worktree
(`/home/hermes/projects/bigquery-duckdb-dbt-experiments/.worktrees/t_d92586d6`,
branch `wt/t_d92586d6`). Read `README.md`, `docs/gaps.md`, `docs/challenges.md`,
`scripts/parity.py`, `scripts/load_duckdb_sources.sh`, `scripts/run_bq.sh`,
`analyses/transport_a/README.md` and `analyses/transport_b/README.md` before you start.
This file is the spec; it is NOT `SPEC.md`, which is the project's design contract —
do not touch `SPEC.md`.

## The goal

Prove, or disprove, that the project produces the **same marts tables** on DuckDB and
BigQuery when both legs read **the same input rows**. Today the DuckDB leg reads a
generated fixture and the BigQuery leg reads the real `bigquery-public-data.thelook_ecommerce`,
so the parity line says "row counts and checksums differ on 28 of them, as expected".
That makes every equality claim a **portability** claim, not a **value** claim. This card
closes that gap.

## Decisions already taken (do not re-litigate them; implement them)

**D1 — Transport A.** The DuckDB leg reads the real rows by materialising the seven
`thelook_ecommerce` tables into local DuckDB tables with the **community `bigquery`
extension** (the path `analyses/transport_a/` measures), not by `EXPORT DATA` → GCS →
Parquet (Transport B). Reasons, to be written into the docs:

* the DuckDB leg then reads real rows through the project's own source declaration, with
  no change to `models/`, `macros/` or `tests/`;
* Transport B inserts a second representation (GCS Parquet) between BigQuery and the DuckDB
  leg, so a value difference could be an export-format artifact rather than a model or
  dialect difference; Transport B also needs a writable bucket and its own committed logs;
* measured on this box (orchestrator, 2026-09-27, before this run): all seven tables,
  510,949,141 bytes, materialised into one scratch DuckDB in **37.0 s** wall, single
  process. The full `orders` table (124,952 rows) alone took 2.29 s.

**D2 — the source type contract.** `models/staging/_thelook__sources.yml` declares that on
DuckDB "all timestamps are absolute instants (BigQuery TIMESTAMP, DuckDB TIMESTAMPTZ)"
and `macros/polyglot/casting.sql:49-51` (`default__to_utc_timestamp`) does
`timezone('UTC', cast(<expr> as timestamptz))`. The extension hands a BigQuery `TIMESTAMP`
back as a **zone-less DuckDB `TIMESTAMP`** (measured: `analyses/transport_a/README.md:179`,
and re-measured by the orchestrator for `thelook_ecommerce.orders`), so a plain copy breaks
the declared contract and every `*_at` column is then shifted by the session offset
(measured on this box, `Europe/Vienna`: `2024-01-02 03:04:05` → `2024-01-02 02:04:05`
through the macro, a **two-hour** shift).

Therefore the loader must deliver the declared type:
`to_timestamp(epoch_us(<col>) / 1000000.0)` — verified by the orchestrator:
`timezone('UTC', to_timestamp(epoch_us(timestamp '2024-01-02 03:04:05')/1000000.0))` =
`2024-01-02 03:04:05` under `set timezone='Europe/Vienna'`.

This is a transport mapping, not a model fix: the raw mapping must also be **measured and
reported** as a finding (a `--raw-timestamps` mode on the loader, and/or a small logged
probe), because it is a real gap between what the extension delivers and what this project's
source contract declares.

**D3 — what is loaded.** All seven tables, every column the real table has, including the two
columns the fixture does not have at all (`users.user_geom`, `distribution_centers.
distribution_center_geom`, both `GEOMETRY('OGC:CRS84')`; re-measured by the orchestrator).
Staging models select named columns, so extra source columns are inert. Report the two extra
columns as a finding (the fixture's schema is a subset of the real one).

**D4 — the comparison.** Compare the **materialised tables on both legs**: the DuckDB leg
is `dbt build --target duckdb` over `dev.duckdb` loaded from BigQuery; the BigQuery leg is
`dbt build --target bigquery` materialising into `coreychimpbot.experiments_dev`. Then for
every model in the project (all 29; every model under `marts/` is mandatory) compare, from
the delivered tables: row count, column names, canonical column types, per-column
order-independent checksum, null count and distinct count — the machinery `scripts/parity.py`
already has, pointed at `experiments_dev.<model>` instead of at an inlined compile. The
existing ephemeral-compile path stays the default and must keep working unchanged for
machines without dataset-write access (`--bq-source compiled|materialised`).

**D5 — duration is a deliverable.** Capture per-model `execution_time` from
`target/run_results.json` after each build (copy it aside immediately: the second build
overwrites it) and report DuckDB time, BigQuery time and the ratio next to each model's
equality result. A model that is value-identical but takes 40× longer on BigQuery is a
finding, not a footnote.

**D6 — a difference is the finding.** Do NOT edit `models/`, `macros/` or `tests/` to make
numbers agree. If the marts differ, the difference goes into `docs/gaps.md` with the raw
output and an attribution (inherent to dual-target SQL / dialect difference such as numeric
type, ordering, null handling / this environment). If they are equal, say so with the
numbers and the comparison method.

## Deliverables (exact paths)

1. `scripts/load_duckdb_real_sources.sh` — the loader (Transport A). Loads the seven real
   tables into `dev.duckdb`, schema `thelook_ecommerce`, honouring D2, verifying each
   table's local row count against BigQuery's `numRows` metadata, printing per-table wall
   time, and failing loudly (exit 1) on any mismatch or any missing prerequisite. Reads the
   key path from `BQ_KEYFILE` (never hard-code it, never print its contents); the data
   project and the billing project are overridable
   (`BQ_DATA_PROJECT`, default `bigquery-public-data`; `BQ_BILLING_PROJECT`, default
   `coreychimpbot`). `--raw-timestamps` loads exactly what the extension returns (for the
   D2 measurement). Every run writes a raw log — see 4.
2. Harness changes in `scripts/parity.py`:
   * `--sources {fixture,real}` (default `fixture`): `real` must **not** re-run
     `scripts/load_duckdb_sources.sh` — that would overwrite the real tables with the
     fixture; it runs `dbt build --target duckdb` only. `fixture` keeps today's behaviour
     (`make duck`, fixture + build) exactly.
   * `--bq-source {compiled,materialised}` (default `compiled`): `materialised` measures
     `<project>.<schema>.<model>` as built by `dbt build --target bigquery`, and runs that
     build first; `compiled` keeps today's ephemeral path exactly.
   * per-model durations (D5) from `target/run_results.json` for both legs, in
     `parity-report.md`, `parity-report.json` and the console summary.
   * `--same-data` gates on row counts and per-column checksums as well as names/types
     (the flag exists; make sure it now actually bites: today it only flips the gating and
     the loader still overwrites the real tables with the fixture).
   * keep the DuckDB-vs-DuckDB baseline, the digest self-check and every existing TRAPS
     behaviour working.
3. `Makefile` targets for the new path (`fixtures-real`, `duck-real`, and a way to run the
   value-parity comparison end to end) with `help` lines; `README.md`'s Running/Makefile
   table stays truthful.
4. `analyses/value_parity/` — the results, in the style of `analyses/transport_a/`:
   * `results.md` — generated, the equality result per mart with the durations;
   * `logs/` — **raw** command output: the loader run, both `dbt build`s (or their
     `run_results.json` copies), the parity run, and the D2 raw-timestamp probe. Raw means
     the actual bytes the commands printed, not a paraphrase.
5. `docs/gaps.md` — §1 ("The two targets read different data") rewritten to the measured
   result; any other gap the run closes or opens; keep the "where each claim comes from"
   table truthful and pointing at real `file:line` sources.
6. `docs/challenges.md` — each challenge this run hit, in the existing shape (real error
   text, `file:line` source, cause, resolution, classification). The card's numbering
   continues the existing 24.
7. `README.md` — the executive summary at the top: replace "value equality ... is what the
   value-equality work is for" with the measured number, the comparison method, and the top
   reasons if the marts differ, pointing at `docs/gaps.md`.

## How the work is run

* Coding goes through **you** (Claude Code, `--model opus`), not the orchestrator. Leave the
  run JSONs in the worktree root as `.cc-value-parity-*.json`.
* The long end-to-end runs (the loader, `dbt build --target bigquery`, `parity.py
  --same-data`) are run by the orchestrator with its own Bash calls, and their raw output is
  what goes into `analyses/value_parity/logs/`. Your job in this invocation is the harness,
  the Makefile wiring and the results-file structure; the orchestrator will report the
  numbers back to you in a follow-up invocation for the docs in 5/6/7.
* `uv sync` has already been run in this worktree (`.venv/bin/dbt` exists). The DuckDB CLI is
  `/home/hermes/.local/bin/duckdb`; `dbc` and the community `bigquery` extension are
  installed. `BQ_KEYFILE` is set for the orchestrator's runs.
* BigQuery costs money: every query goes through `maximum_bytes_billed` (1 GB in
  `profiles.yml`); the loader's table reads go through the Storage Read API and are not
  query jobs. Do not raise the ceiling.
* Never print, copy or commit the service-account key. Never commit `dev.duckdb`,
  `parity-report.*` or anything under `logs/`.
* Keep the repository's existing style: comments that explain *why*, sentences in the docs
  that say what was measured and what was not, no invented numbers.

## Verification you must run yourself before reporting

* `bash scripts/check_env.sh`, `bash scripts/load_duckdb_sources.sh` (fixture path unchanged),
  `python3 scripts/check_portability.py`, `bash scripts/polyglot_check.sh` — all green.
* `python3 scripts/parity.py --skip-build` against the fixture still behaves as before
  (schema parity, value differences reported, exit 2 without a key).
* The new loader against the real dataset, and `python3 scripts/parity.py --sources real
  --same-data` end to end, with the raw output captured.
* `git diff` reviewed by you; no model, macro or test file changed.
