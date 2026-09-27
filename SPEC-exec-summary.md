# SPEC — card t_c7189126: rewrite the top of README.md as an executive summary

## The one question the top of `README.md` must answer

*How close is this project to being identical on BigQuery and DuckDB, and what are the top reasons
it is not?* Readable in thirty seconds. Honest about what is measured versus assumed.

## Method constraints (read carefully, they are the whole job)

- **Docs only.** The only file you may edit is `README.md`. Do not touch models, macros, scripts,
  Makefile, docs/challenges.md, docs/gaps.md, SPEC.md.
- **Do not run any build, test, parity, portability or dbt command.** Every number you need is
  already measured and is given to you below, or is already in `README.md` on this branch. Do not
  re-derive anything, do not run experiments, do not install anything.
- **Do not invent a number.** If a fact is not in this spec and not already in the working tree, do
  not write it.
- **No fact may be lost.** Every number and every named fact that appears in the current top of
  `README.md` (everything above `## Layout`) must still appear somewhere in the new top. You may
  move, merge and shorten prose, but nothing may be silently dropped.
- **Author voice**: the repo's existing register — plain, declarative, concrete, no marketing. Read
  the current `README.md` top and `docs/challenges.md` first and match it.

## Required structure of the new top of `README.md`

Keep, in this order:

1. `# bigquery-duckdb-dbt-experiments` (unchanged)
2. The "one dbt v2 project, two targets" framing paragraph (paragraph 1, keep verbatim — it ends
   with Sean's *"one single project power both with using macros to help transpile."*)
3. **NEW BLOCK — the executive summary.** Add a `## ` heading (suggest
   `## How close are the two targets?`) directly **above** the current `**Status: ...**` paragraph.
   This is the deliverable: roughly 250-350 words plus the numbered list, skimmable in thirty
   seconds.
4. The status paragraph — **shrink it**. It currently repeats the model-layer breakdown, the test
   counts and the credential detail. Once the summary carries "how close" and the build numbers,
   this paragraph keeps only what a runner needs: that the tree builds on both targets, the DuckDB
   leg reads a **generated fixture** (invented data, real schema) unless `make fixtures-real` swaps
   the real rows in, and that BigQuery is **runnable with a named credential** (`BQ_KEYFILE` →
   `~/.config/gcp/coreychimpbot-sa.json`, or `GOOGLE_APPLICATION_CREDENTIALS`, or `profiles.yml`),
   which is not ambient, and that without one `make bq` exits 2 with an explanation rather than an
   authentication error. Keep the fixture paragraph's substance — do not re-introduce the retired
   "BigQuery never runs here" claim.
5. The macro-seam paragraph (**keep verbatim** — the paragraph beginning "The transpile seam is
   **28 macros** in `macros/polyglot/`").
6. `## Layout` and everything below it — untouched.

The current **"Value equality, measured on one dataset: ..."** paragraph (added by the value-parity
card) is **absorbed into the new summary** — its numbers move up into the summary's values section
and the type/rounding reason. Delete it as a standalone block; do not duplicate it. Its facts are
listed below and must all survive.

## The facts to write the summary from (all already measured — copy them, do not recompute)

### How close it is (structure)

- **All 29 of 29 models are a single source file each** — no fork, no `target.type` branch, no other
  engine's dialect in either render.
- `scripts/check_portability.py` prints `compiled files checked: 30 (models: 29, analyses: 1)`,
  `BigQuery-only tokens in the DuckDB render: 0/15`, `DuckDB-only tokens in the BigQuery render:
  0/13`, `target-branch findings: 0`, `PORTABLE`, exit 0.
- Both targets build today: DuckDB `196 total | 196 success`; BigQuery `196 total | 195 success |
  1 warn`, 2m 9s, exit 0 (2026-09-27, with the service-account key).
- The guardrail's 30 files are **29 models plus 1 analysis** (the showcase). `analyses/` also holds
  **60 transport-measurement `.sql` scenarios** (Transport A: 22, Transport B: 38) excluded from the
  scan **by name** (`EXCLUDED_ANALYSES` in `scripts/check_portability.py`) because they are
  deliberately engine-specific. Say this so nobody reads the guardrail's 30 files as the whole
  project. (61 `.sql` files under `analyses/` in total = 60 excluded + 1 scanned.)

### How close it is (values) — measured, and the headline number

- `make value-parity` (2026-09-27, `scripts/parity.py --sources real --bq-source materialised
  --same-data`) ran **one dataset through both legs**: the seven real
  `bigquery-public-data.thelook_ecommerce` tables copied into `dev.duckdb` through the community
  `bigquery` extension (every row count equal to BigQuery's `numRows`), both targets built over those
  same rows (`196 total | 195 success | 1 warn` on each), then every materialised relation compared:
  row count, column names and canonical types, and per column an order-independent checksum, a null
  count and a distinct count.
- Result: **row counts identical on all 29 models; 8 of 29 models identical on every check; 1 of the
  11 marts (`dim_date`).** 21 models differ, in 55 columns — all `money_type()` columns except one
  rate derived from them (`mart_product_performance.gross_margin_rate`). **0 row-count differences,
  0 null-count differences, 0 name/type differences.**
- The reason is where the rounding happens: `money_type()` is `decimal(18,2)` on DuckDB, which rounds
  the source's `FLOAT64` prices and costs to cents, against `numeric` on BigQuery, which keeps nine
  decimal places. **29,035 of the 29,120 real `products.cost` values are not whole cents on
  BigQuery.** DuckDB `decimal(18,2)` renders `12.30` where BigQuery `numeric` renders `12.3`;
  rounding BigQuery to cents reconciles **23 of the 55** differing columns; the other 32 (cost, and
  what is computed from it) still differ.
- Durations, recorded next to the equality result: the same 29 models took **19.96 s** of dbt model
  time on DuckDB and **230.25 s** on BigQuery (11.5x; up to **62.0x** for one model,
  `stg_thelook__users`).
- The default `make parity` still reads the fixture on the DuckDB side; its figures — 28 of 29
  differ, `stg_thelook__distribution_centers` matches — describe that fixture path only, **not** a
  portability difference.
- Evidence: `analyses/value_parity/` (`results.md`, `results.json`, raw `logs/`) and
  [`docs/gaps.md`](docs/gaps.md) §1.

### The top reasons they are not identical (the summary's numbered list, in this order)

1. **Money's scale, and one type-fidelity mismatch behind it.** The measured difference above:
   `decimal(18,2)` vs `numeric`. The one mismatch that made `make parity` exit 1 was `SAFE_DIVIDE`,
   which returned `DOUBLE` on DuckDB and `NUMERIC` on BigQuery (`parity: MISMATCH. gating:
   ['mart_product_performance']`); fixed by casting both sides to `float_type()` on the BigQuery
   branch in `macros/polyglot/math.sql`. The two `average_order_value` money metrics are a
   **deliberate exception**, keeping `round(x / nullif(y, 0), 2)` as `money_type()`.
2. **A boolean in `accepted_values`.** dbt quotes the literals, so BigQuery got
   `BOOL not in ('True','False')` and **errored** (`Error 400: No matching signature for operator IN
   for argument types BOOL and {STRING}`), where DuckDB coerces. The test was removed — `not_null`
   covers a computed boolean — and the trap is recorded in the column description so nobody re-adds
   it.
3. **`BIGNUMERIC` has no DuckDB equivalent.** DuckDB's `DECIMAL` stops at 38 digits, BigQuery's
   `BIGNUMERIC` carries 76.76. In files it **narrows to a `double` silently** — 16 significant digits
   of 38, no error or warning — and through the extension it arrives as `VARCHAR`. No model has a
   `BIGNUMERIC` column, so nothing is currently exposed to this.
4. **Date and time semantics** — four separate trap families, all now in macros: `unnest`'s alias in
   `FROM` and the series' element type (`TIMESTAMP[]`); month steps drifting from a month-end start;
   normalisation in the date/time helpers; and `day_of_week_iso`'s render.
5. **One live warning on real data.** `assert_order_item_created_at_is_plausible` **passes on the
   fixture and warns on the real dataset** — a fixture assumption the real data contradicts. It is
   `severity: warn` deliberately.
6. **BigQuery's export semantics**, which matter only if the file route is used: an unordered
   export's row order is **not reproducible**; CSV cannot carry nested or repeated types;
   JSON→Parquet is refused (though JSON→CSV works).

### The seam's size (one short paragraph or sentence, for scale)

28 macros in `macros/polyglot/`; **148 seam call sites across the 29 models** (mean 5.10 per model,
max 15 in `stg_thelook__users`), 175 including the showcase analysis
(`analyses/polyglot_showcase.sql`, 27 more); 25 of 29 models call a seam macro; 16 of the 26 dialect
macros are called by a model; and across the 11 marts only **one** new primitive was needed
(`dim_date`, from the date-spine traps above).

### Close the summary with

Detail lives in [`docs/challenges.md`](docs/challenges.md) (every challenge, with the real error
text) and [`docs/gaps.md`](docs/gaps.md) (what could not be established, and why). Both links must
be present, as relative links.

## Acceptance criteria (the checker will run these)

1. The only modified file is `README.md`.
2. `README.md` still starts with `# bigquery-duckdb-dbt-experiments`, followed by the framing
   paragraph verbatim, then the new summary heading, then a (shorter) status paragraph, then the
   macro-seam paragraph verbatim, then `## Layout`.
3. `grep -n '^## ' README.md | head` shows the new summary heading above the status text.
4. Every number listed in this spec appears in `README.md`; every number that was in the old top of
   `README.md` still appears somewhere in the top region.
5. No diff outside `README.md`.
