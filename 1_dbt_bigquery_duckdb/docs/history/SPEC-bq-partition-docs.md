# Card t_55f119de, phase 3 — record the measurement in the repository's own notes

## Context

Phase 1 added the seam (`macros/polyglot/physical.sql`, `physical_layout()`) and applied it to
`models/marts/fct_inventory_items.sql`. Phase 2 added the harness
(`scripts/bq_partition_measure.py`, `make partition-measure`) and the method
(`analyses/partitioning/README.md`). Both are done and verified.

The orchestrator has now run the whole thing on real BigQuery. **This phase only writes it down.**
Every number below was read from the BigQuery jobs API by that harness and is in
`analyses/partitioning/results.md`, `analyses/partitioning/results.before.json`,
`analyses/partitioning/results.after.json` and `analyses/partitioning/logs/{before,after}.log`.
Use only these numbers. Do not round them differently, do not infer anything they do not say, and do
not invent a number for anything marked unmeasured below.

## The result, verbatim

* Target model and table: `fct_inventory_items`, largest fact table by both measures —
  488,895 rows / 49,525,078 bytes, against `fct_order_items` 181,070 rows / 45,581,586 bytes
  (BigQuery table metadata, 2026-10-07).
* Seam: `macros/polyglot/physical.sql`, `physical_layout()`; the model carries
  `{{ config(**physical_layout()) }}`, which on BigQuery is
  `partition_by = {field: created_at, data_type: timestamp, granularity: day}` and
  `cluster_by = [product_id]`, and on DuckDB is nothing (the macro's default branch returns an empty
  dict).
* Measured dataset: `coreychimpbot.experiments_partition`, window `2024-06`. Before leg built from a
  scratch copy under `target/partition_before/` (identical tree with only that config line removed);
  after leg built by the real tree.
* Every executed job ran with `useQueryCache: false` and `maximumBytesBilled: 1000000000`
  (the 1 GB ceiling from `profiles.yml` is unchanged), and every one reported `cacheHit: false`.

| query | bytes processed before | bytes processed after | bytes billed before | bytes billed after |
|---|---:|---:|---:|---:|
| `full_scan`: `SELECT *` (no filter) | 49,525,078 | 49,525,078 | 50,331,648 | 50,331,648 |
| `filtered_scan`: `SELECT *` where `created_at` in 2024-06 | 49,525,078 | 592,415 | 50,331,648 | 10,485,760 |
| `filtered_count`: `COUNT(*)` over the same filter | 3,911,160 | 46,728 | 10,485,760 | 10,485,760 |
| `dry_run` estimate of `filtered_scan` (bills nothing) | 49,525,078 | 592,415 | — | — |

* `filtered_scan` delta: processed **-98.8 %** (49,525,078 → 592,415), billed **-79.2 %**
  (50,331,648 → 10,485,760). The filtered query read 100.0 % of the full scan before and 1.2 %
  after.
* The billed delta is smaller than the processed delta because BigQuery bills a **10 MiB minimum per
  query**: the after leg's filtered scan billed 10,485,760, the floor. `filtered_count` shows the
  same floor from the other side — its processed bytes fell -98.8 % and its billed bytes did not
  move at all (10,485,760 in both legs).
* `full_scan` is the control: identical bytes both times, so the two tables hold the same rows.
* Table metadata after (`tables.get`): `timePartitioning type=DAY field=created_at`, clustering
  `product_id`. Before: `timePartitioning: none`, clustering `none`.
* Rows per partition (`INFORMATION_SCHEMA.PARTITIONS`): before, one row with a NULL `partition_id`
  holding all 488,895 rows (an unpartitioned table); after, **2,826 day partitions** from
  `20181121` to `20261010`, 488,895 rows over them, of which the measured month `2024-06` is
  **30 partitions holding 5,841 rows**.
* The BigQuery leg itself, `DBT_ENV=partition make bq` (exit 0):
  `Processed: 30 models | 168 tests` / `Summary: 198 total | 197 success | 1 warn`. The one warning
  is the intended `severity: warn` test `assert_order_item_created_at_is_plausible`, which fires on
  the real data and is documented as such.
* The DuckDB leg, unchanged: `dbt build --target duckdb` →
  `Processed: 30 models | 168 tests` / `Summary: 198 total | 198 success`.
* `make portability`: `PORTABLE`, 0 BigQuery-only tokens in the DuckDB render (0/15), 0 DuckDB-only
  tokens in the BigQuery render (0/13), 0 target-branch findings, 31 compiled files (30 models,
  1 analysis).
* Job ids of the representative filtered query, for anyone re-reading the numbers:
  before `job_--eUTegE5ZnzLQC2JBQAGWRkayPs`, after `job_pHUPQzT6gH9cgWuH-n3o90457FvT`.

**Unmeasured, and it must be said as such:** clustering's own byte effect was **not isolated**. No
measured query filters on `product_id` alone, and on a table of this size (one block per partition)
BigQuery's clustering has nothing to prune that partition pruning has not already removed. What is
established about clustering is only that the table's metadata reports the cluster column
(`product_id`) and that the table built with it.

## Work — four documents, nothing else

### 1. `NOTES.md` — a new section, after the last one

`# Card t_55f119de — partitioning and clustering on the largest fact table, measured`. The
repository's running record: why the card existed (the gaps document said the BigQuery write path was
a plain build with no partitioning, no clustering, and a cost ceiling never reached), what was built
(the seam, the model line, the harness), the table above with its numbers, the commands that produced
them, and a "What this does not establish" list — the clustering effect above, the one-table
one-query scope, the 10 MiB floor, and the fact that the before leg is a scratch copy rather than a
build of record.

### 2. `docs/gaps.md`

* The **section 2 table**: the `Partitioning and clustering` row says the warehouse uses neither and
  is "Unverified". Replace it with the measured result — the keys, partition pruning's effect on the
  representative filtered query (processed -98.8 %, billed -79.2 %), the 2,826 partitions, the
  metadata confirmation, and the one thing left unmeasured (clustering's own byte effect).
* The `DDL beyond a plain build` row: it says "Nothing about table options, incremental models or
  concurrency was tested". Table options are now exercised (partitioning and clustering on one mart);
  the rest still is not. Say both halves.
* The **intro paragraph** ends "...and no partitioning or clustering is used". Correct it.
* The **"Where each claim comes from"** table at the end: add a row for the partitioning numbers,
  pointing at `analyses/partitioning/results.md` (and the `results.{before,after}.json` + `logs/`),
  and one for the seam/`make portability` figures if the existing rows do not already cover them.
* Keep the document's own two-word convention (**unverified** = nothing was run that could fail;
  **broken** = a run failed) exactly as it uses it elsewhere.

### 3. `docs/move_to_duckdb.md`

Section 5 lists `partition_by` / `cluster_by` as constructs that "cannot move at all", and says the
detector looks for them. That is still true of the **literal** config keys — and the reason this
card's model carries neither literally: `physical_layout()`'s default branch returns an empty dict,
so the move renders the model as a plain table with no key to detect. Add that to the section, in the
document's voice: the two rules still fire on a literal `partition_by =` / `cluster_by =`, and the
seam is what keeps this project's one partitioned model portable. Do not change the detector, do not
change the "In this project: the source has 1 finding" sentence unless it is now wrong (it is not —
check it against `models/staging/_thelook__sources.yml`).

### 4. `README.md`

* The `Repository map` table: add `macros/polyglot/physical.sql` (the physical-layout seam: whether
  `macros/polyglot/` is described as the cross-engine seam already, extend or add a row),
  `scripts/bq_partition_measure.py` and `analyses/partitioning/`, in the same one-line style as their
  neighbours.
* `### Common commands`: add `make partition-measure` to the list and one clause saying what it does
  and that it needs `BQ_KEYFILE`.
* "What was actually proven" (`### 1)` bullet list, "The portability seam is small enough to be
  practical"): add one bullet for the physical layout — partitioning and clustering for BigQuery
  expressed as a seam macro whose DuckDB branch is empty, with the measured effect
  (processed -98.8 %, billed -79.2 % on one month of a 488,895-row fact table) — matching the
  bullet style of array/struct/JSON above it.
* Do **not** correct the pre-existing stale model counts elsewhere in the file (29/30, etc.): they
  are recorded in `docs/gaps.md`'s documentation section as a separate known issue and are out of
  scope here.

### 5. `analyses/partitioning/README.md`

Its header list still says "results: filled in by the measurement phase of this card". Point it at
`results.md` (and the two JSON files beside it) now that they exist.

## Constraints

* Use only the numbers above; if something is not above, write it as unmeasured, not as a guess.
* Keep each document's existing voice, table style and cross-reference style. No new headings
  sections would not expect, no emoji, no marketing.
* No Jinja delimiters in anything under `analyses/`.
* Do not touch models, macros, scripts, the Makefile, profiles.yml or the SPEC files.

## Verify

* `git diff --stat` and the full diff.
* `.venv/bin/dbt compile --target duckdb --target-path target/doccheck` exits 0 and the
  `MacroSyntaxInvalid` warning still points only at `analyses/value_parity/rows.md` (proof that
  nothing under `analyses/partitioning/` introduced one).
* `python3 scripts/check_portability.py` still prints `PORTABLE`, 0 findings.
