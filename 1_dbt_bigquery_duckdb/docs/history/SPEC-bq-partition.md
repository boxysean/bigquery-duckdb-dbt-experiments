# Card t_55f119de — exercise BigQuery partitioning and clustering (phase 1: the seam and the model)

## Goal

Add partitioning and clustering to the largest fact table, through the shared macro layer
(`macros/polyglot/`), so the DuckDB leg still builds unchanged and nothing in `models/` branches on
the target. This phase is the seam and the model only; the BigQuery measurement harness and the
documentation are a second phase, run by the orchestrator afterwards.

## Decisions already made (do not re-litigate, do not redesign)

* Largest fact table, measured from BigQuery table metadata on 2026-10-07:
  `fct_inventory_items` 488,895 rows / 49,525,078 bytes, versus `fct_order_items` 181,070 rows /
  45,581,586 bytes. The card's target model is `models/marts/fct_inventory_items.sql`.
* **One** new macro file, `macros/polyglot/physical.sql`, defining `physical_layout()`, following the
  exact shape of the entries in `macros/polyglot/types.sql`: a public entry macro that
  `adapter.dispatch`es to `default__physical_layout` / `bigquery__physical_layout`, with a
  `{# ... #}` header comment in the same voice as its neighbours explaining the divergence and the
  `{{ return(...) }}` contract.
  * `default__physical_layout()` returns an **empty dict** `{}`: on DuckDB the model gets no physical
    layout at all. That is the seam's whole point, and it is honest — the keys below exist on no
    other engine.
  * `bigquery__physical_layout()` returns exactly
    `{'partition_by': {'field': 'created_at', 'data_type': 'timestamp', 'granularity': 'day'}, 'cluster_by': ['product_id']}`.
* The model applies it by splatting the dict into the existing `config()` call, so the literal words
  `partition_by` / `cluster_by` never appear anywhere under `models/`. Two things depend on that:
  `scripts/check_portability.py` (purity scan) and `scripts/move_to_duckdb.py`'s detector (rules
  `partition_by` / `cluster_by` match the literal `partition_by =` text).
* No `target.type` / `adapter.type` branch anywhere. The dispatch is the dialect seam, as everywhere
  else in this project.

## Work

1. **`macros/polyglot/physical.sql`** (new) — as above. State in the header comment what each branch
  returns and why the default is empty.
2. **`models/marts/fct_inventory_items.sql`** — add the config line at the top of the file, above the
  `select`, in the same style as the other marts. The model has no `config()` call today; the
  materialisation comes from `dbt_project.yml` (marts are tables), so the call adds only the physical
  layout. Do not change any column, filter or join.
3. **`models/marts/_marts__models.yml`** — extend the `fct_inventory_items` `description` with one
  sentence saying the table is partitioned by `created_at` (day) and clustered by `product_id` on
  BigQuery, through the `physical_layout()` seam, and that DuckDB gets a plain table.
4. **`analyses/partitioning/README.md`** (new) — the measurement protocol for this card, in the same
  register as `analyses/transport_a/README.md` and `analyses/value_parity/README.md`: why the two
  engines diverge here, what will be measured (bytes processed and bytes billed for one
  representative filtered query, before and after, read from the jobs API), the partition and
  cluster keys, and the constraint that the 1 GB `maximum_bytes_billed` ceiling stays in place. The
  numbers themselves are filled in by a later phase; state the method now.
5. Change **nothing else**. No new model, no new test, no profile change.

## Constraints

* Never put a billable query into a dbt test.
* **No Jinja delimiters (`{{` or `{%`) inside any file under `analyses/`.** dbt parses `.md` files
  there as analyses and emits a `MacroSyntaxInvalid (dbt1502)` warning for them (see
  `analyses/value_parity/rows.md:79`). Describe the macro in prose, not as a code sample.
* The DuckDB leg must still build green.

## Verify — run these and report the real output

* `.venv/bin/dbt compile --target duckdb` ; then show that the `fct_inventory_items` node inside
  `target/manifest.json` has **no** `partition_by` in its config (only the macro source text in the
  manifest mentions it).
* `.venv/bin/dbt compile --target bigquery` ; then show that the same node's config **does** carry
  `partition_by` (field `created_at`, day granularity) and `cluster_by` (`["product_id"]`).
* `.venv/bin/dbt build --target duckdb` — model and test counts, exit status.
* `python3 scripts/check_portability.py` — must print `PORTABLE`, 0 findings.
* `git diff --stat` and the full `git diff` of the two changed model files.

Run with `DBT_PROFILES_DIR` set to the repository root and `.venv/bin/dbt` (already synced). The
`.md` warning above is pre-existing and expected; do not "fix" it.
