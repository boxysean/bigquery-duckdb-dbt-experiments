# SPEC: row-by-row join of the two legs (card t_48e969eb)

Close the last unmeasured claim in the value-parity work: **join the DuckDB leg and the
BigQuery leg row by row** on each model's key, for the money columns only, and say whether
any row holds genuinely different money rather than the same money at a different declared
scale.

Read `docs/gaps.md` §1, `analyses/value_parity/results.md`, `scripts/parity.py`,
`macros/polyglot/types.sql` and `analyses/value_parity/probes/*.py` before designing.

## What is already established — do NOT re-derive, do NOT re-measure the whole parity run

`make value-parity` (2026-09-27, `analyses/value_parity/results.md`) compared all 29 models
over the same real `thelook_ecommerce` rows: 29/29 row counts equal, 0 null differences,
no column-name/type/key difference, 8 of 29 models match on every check (1 of 11 marts),
21 models differ in 55 columns — every one a `money_type()` column plus
`mart_product_performance.gross_margin_rate`. Cause: `money_type()` is `decimal(18,2)` on
DuckDB and nine-decimal `numeric` on BigQuery (`macros/polyglot/types.sql:85-91`) while the
source prices/costs are `FLOAT64`; 29,035 of 29,120 `products.cost` values are not whole
cents on BigQuery. Rounding BigQuery to cents reconciles 23 of 55 columns; 32 still differ.

## Facts verified on the box before writing this spec (trust them, re-check cheaply if useful)

* The BigQuery leg of record is still materialised and untouched: `coreychimpbot.experiments_dev`
  holds 29 relations, created 1790548414484 ms (2026-09-27T19:13:34Z), row counts identical to
  `results.md` (dim_date 2813, dim_products 29120, fct_inventory_items 489625, …). 19 are
  TABLES (the fct_/dim_/mart_ models), 10 are VIEWS (staging and intermediate).
* The DuckDB leg is already built **in this worktree**: `dev.duckdb` holds the real source rows
  (`thelook_ecommerce` schema, loaded by `scripts/load_duckdb_real_sources.sh`, log
  `analyses/value_parity/logs/row_join_loader.log`) and `dbt build --target duckdb` produced all
  29 models in schema `main`: `196 total | 195 success | 1 warn` — the same as the of-record run.
* The community `bigquery` extension (1.5.5, build from community) can read the leg **inside
  DuckDB**: `bigquery_scan('<project>.<dataset>.<table>', billing_project := …)` reads a TABLE
  through the Storage API (no query job) and returns a BigQuery `NUMERIC` as `DECIMAL(38,9)` —
  i.e. exactly the declared nine decimals. Readings verified: `dim_products.unit_cost`
  product 1 = `27.047999916`, `stg_thelook__products.cost` product 1 = `27.047999916`.
* **`bigquery_scan` cannot read a VIEW**: `Binder Error: Error while creating read session:
  Permanent error, with a last message of request failed: non-table entities cannot be read with
  the storage API`. `bigquery_query('<project>', '<sql>', billing_project := …, use_rest_api := true)`
  does read a view (query job) and also returns `DECIMAL(38,9)`.
* `BQ_KEYFILE` is `/home/hermes/.config/gcp/coreychimpbot-sa.json`. `maximum_bytes_billed` is
  1 GB per query and must stay `scripts/parity.py`'s `MAX_BYTES`.
* No `pyyaml` in `.venv`, and no `dbt_utils`: keys must come from dbt's own `target/manifest.json`
  (the `unique` generic tests), not by parsing YAML.
* Nothing in this card may change a published model or macro except as an explicitly marked,
  **unapplied** proposal.

## Design (decided — implement this, do not invent a different measurement)

Three legs over the same rows:

| leg | what it is | how it is obtained |
|---|---|---|
| `L2` | the DuckDB leg of record: `money_type()` = `decimal(18,2)`, schema `main` in `dev.duckdb` | already built; the script must **check** it is there and refuse to run otherwise |
| `L9` | the same DuckDB build with `money_type()` overridden to `decimal(38,9)` — an emulation of BigQuery's declared scale on the DuckDB path | built by the script into schema `money9` of a copy of `dev.duckdb`, from a scratch copy of the project whose **only** difference is `default__money_type()` → `decimal(38,9)`; the repository itself is never edited |
| `BQ` | the BigQuery leg of record: `coreychimpbot.experiments_dev` | read into DuckDB (schema `bq_leg`) with `bigquery_scan` for tables and `bigquery_query` for views |

Why `L9` exists: it is the only way to decide, for a *derived* money column, whether the cent
difference is the declared scale propagated through arithmetic, or something unexplained. If
`L9` reproduces `BQ` row for row at nine decimals, the difference is the declared scale and
nothing else. If it does not, that row is unexplained and must be reported as such.

Steps, per model with at least one money column:

1. **Gate that the BigQuery leg is the leg of record.** Using `scripts/parity.py`'s own
   `BigQueryLeg.query` and `Engine.canon`, recompute the BigQuery-side checksum, null count and
   distinct count (exactly as `parity.py` does) for every money column in
   `analyses/value_parity/results.json`, and compare with the `bigquery` values recorded there.
   Any mismatch → stop, the join would be measuring a different leg.
2. **Key.** Take the model's key column from `target/manifest.json`'s `unique` test (one per
   model; verify there is exactly one and that it is not a money column).
3. **Money columns.** DuckDB columns of `main.<model>` whose type is `DECIMAL(18,2)`; cross-check
   the BigQuery relation's schema says `NUMERIC` for the same names. Handle
   `mart_product_performance.gross_margin_rate` (`float_type()`, derived from money) as a
   named special case, and say in the report how it is compared.
4. **Pull the BigQuery side in** as `bq_leg."<model>"(key, money columns…)`.
5. **Join** `L2`, `L9` and `BQ` on the key with a FULL OUTER JOIN and assert: row counts equal on
   all three, 0 keys unmatched on either side. A NULL key or a duplicate key is a finding.
6. **Per model, per column, report** (this is the deliverable the card names):
   * rows compared; rows where the cents differ (`round(BQ, 2) != L2`); rows where the raw value
     differs at all (`BQ != L2`);
   * **the distribution of the difference in cents**, not just a max: a table of
     `delta_cents → rows` for every delta present (e.g. `-0.01 → 3, 0 → 29,117, +0.01 → 0`);
   * a handful of example keys with both sides' values at full width (at most 5 per column);
   * the bucket counts below.
7. **Classification — every difference lands in exactly one bucket:**
   * **A — declared scale, cents agree**: `round(BQ, 2) = L2`. Same money, different declared scale.
   * **B — declared scale, propagated (the rounding path)**: `round(BQ, 2) != L2` **and** `L9` at
     nine decimals equals `BQ` on that row, i.e. the whole difference is the declared scale, and
     the cent the two legs land on differs because one path rounds the source `FLOAT64` once and
     the other rounds it through nine decimals (`round(raw)` vs `round(round_9(raw))`).
   * **C — unexplained**: everything else — the two legs hold different money for the same key at
     any scale even after the declared scale is emulated. Report the keys and both values.
   Counts per bucket per column, and a model-level and project-level total.
8. **The base-value control, independently of `L9`**: on `dev.duckdb`'s copy of the raw
   `FLOAT64` sources, count how many values change cent between `cast(x as decimal(18,2))` and
   `round(cast(x as decimal(38,9)), 2)` for `products.cost`, `products.retail_price`,
   `order_items.sale_price`, `inventory_items.cost`, `inventory_items.product_retail_price`.
   The known figure for `products.cost` is 1 of 29,120 (`6.644999999552965`); confirm or correct it.
9. **The answer, stated with numbers**: is there any row where the money is genuinely different
   money? Yes/no, the count, and example keys if yes.
10. **The proposal (unapplied)**: if every difference is A or B, show the exact one-line diff that
    would make both legs agree — `macros/polyglot/types.sql`'s `default__money_type()` — and say
    what `L9` proves about it. Leave it **out of the commit** or in a separate commit whose sole
    content is that proposal; do not change any published value otherwise.
11. Any new challenge (real error text, `file:line`, cause, resolution, attribution) into
    `docs/challenges.md`, in the existing shape.

## Deliverables (files)

* `scripts/row_join.py` — the measurement (or, if the plan argues for it, an equally documented
  home; state which and why).
* `analyses/value_parity/rows.md` and `analyses/value_parity/rows.json` — the results, in the style
  of `results.md` (verdict, per-model table, the full per-column difference tables, the
  classification, the answer, the proposal).
* raw logs under `analyses/value_parity/logs/rows/` — the join's own output, per model if useful.
* a `make` target that runs it (the repo documents every entry point in `make help`), only if it
  costs nothing new to run: the DuckDB legs and the `L9` copy are local, the BigQuery reads are
  the Storage API plus a few small view jobs.
* `docs/gaps.md` §1 edits: the "which rows differ, and by how much — unmeasured" row replaced by
  the measured answer, and the money row's figures corrected if they move. Keep the existing style.
* `README.md`: only if a claim in it becomes false. Do not rewrite it otherwise.

## Constraints

* Do not touch `analyses/value_parity/results.md` / `results.json` / `logs/loader.log` or the
  existing probe logs — they are the of-record evidence of the earlier card. New run, new files.
* Never modify a published model, macro, test or profile in the repository except the unapplied
  proposal in item 10.
* Everything must be reproducible from a clean checkout plus `BQ_KEYFILE`: no absolute paths in
  the committed script other than through environment variables.
* Cost: keep every BigQuery read inside `maximum_bytes_billed` (1 GB) and prefer the Storage API.
* Quote real output. Nothing in the report may be an estimate or an extrapolation.