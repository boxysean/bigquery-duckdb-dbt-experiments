# Gaps: what could not be established here, and why

**Cross-engine value parity is now measured, and it does not hold for money.** On the same
input rows, row counts are equal on all 29 models, but values are equal on 8 of 29 and on 1
of the 11 marts. Joined row by row (2026-09-28), no row holds genuinely different money:
every cent that differs is BigQuery's nine-decimal `numeric` propagated, reproduced exactly
by a DuckDB build with the same declared scale. The next largest is the BigQuery
write path beyond a plain build: it now materialises all 29 models and is priced, the cost
ceiling has refused a query only at a deliberately tiny setting, and partitioning and
clustering are used on one mart only (`fct_inventory_items`), where partition pruning is
measured and clustering's own effect is not. Most of the other gaps are
documented limits that were never reached, not failures.

Two words are used deliberately below:

* **Unverified** means nothing was run that could fail. It does not mean broken.
* **Broken** means a run failed. No gap listed here is broken, except where a measured
  failure is quoted.

Related documents: [`challenges.md`](challenges.md) covers what was hit, and
[`move_to_duckdb.md`](move_to_duckdb.md) §9 covers the fallback's own gaps. The table at the
end maps every gap to its source.

## 1. Value parity on one dataset

`make value-parity` (2026-09-27) loaded the seven real `thelook_ecommerce` tables into
`dev.duckdb` through the community extension, built both targets over them (both
`196 total | 195 success | 1 warn`) and compared the materialised relations of all 29
models: row count, column names, canonical types, and per column an order-independent
checksum, a null count and a distinct count. The digest self-check passed and the
DuckDB-vs-DuckDB baseline matched. Evidence: `analyses/value_parity/` (`results.md`,
`logs/`). The default `make parity` still reads the fixture on the DuckDB side; its
figures (28 of 29 differ, `stg_thelook__distribution_centers` matches) describe that path
only.

The same measurement was repeated on 2026-09-28 over a fresh load, with the BigQuery leg
in `coreychimpbot.experiments_rows` (`analyses/value_parity/fresh/`: 8 of 29 match, marts 1
of 11, row counts equal on every measured model), because the public source had grown
since the first run (row "Source drift" below). `make row-join DBT_ENV=rows`
(`scripts/row_join.py`, `analyses/value_parity/rows.md`) then joined that pair row by row on
each model's key, for all 55 money columns of the 21 models that hold one, against a third
leg: the same DuckDB build with `money_type()` = `decimal(38,9)` (L9, built from a scratch
copy; the repository is unchanged).

Closed by this run: **surrogate-key values across engines**. The three key columns
(`product_center_key`, `user_month_key`, `cohort_activity_key`) are not among the
differences, so their checksum, null count and distinct count agree on both legs.

| gap | why it could not be established | size |
|---|---|---|
| **Cross-engine value parity (money)** | **Closed on 2026-10-07** by `money_type()` = `decimal(38,9)` and `money_quotient()`: 30 / 30 relations equal to BigQuery row for row, 0 of 79,839,931 cells different ([`analyses/money_fix/README.md`](../analyses/money_fix/README.md)). What follows is the measurement before the fix. Measured, and it fails: the same SQL over the same rows gives different money. `money_type()` is `decimal(18,2)` on DuckDB and `numeric` (nine decimals) on BigQuery (`macros/polyglot/types.sql:85-91`), and the source prices and costs are `FLOAT64`, so DuckDB rounds to cents where BigQuery keeps sub-cent digits (29,035 of 29,120 `products.cost` values are not whole cents on BigQuery). Inherent to dual-target SQL (numeric type). | Row counts equal on **29 of 29**. **8 of 29** match on every check; marts **1 of 11** (`dim_date`). 21 models differ in 55 columns, all money columns except `mart_product_performance.gross_margin_rate` (distinct values: 18,699 DuckDB, 328 BigQuery; 18,693 and 328 on the fresh pair); 0 row-count, 0 null-count and 0 name/type differences. Rounding BigQuery to cents reconciles 23 of the 55 columns; 32 (cost and what is computed from it) still differ. The fresh pair's row join confirms the split row by row: 23 columns have 0 rows whose cents differ, 32 have at least one; every one of the 55 differs in raw value on at least 10 rows. |
| **Which rows differ, and by how much** | Measured on the fresh pair (2026-09-28) by joining both legs and L9 on each model's key. Every compared row lands in one bucket: identical, **A** same cents at a different declared scale, **B** the cents differ and L9 reproduces BigQuery exactly, **C** anything else. | **0 rows of genuinely different money (C = 0).** 6,605,909 column-rows over 55 columns: identical 1,564,764, A 4,767,319, B 273,826, C 0; 0 unmatched, NULL or duplicate keys; 0 rows NULL on one leg only. Cent differences per column range from +0.01 only (`unit_cost`, `product_cost`) to -8.99..+0.19 (`dim_distribution_centers.open_inventory_value`, a sum over whole centres). At the base, 1 of 29,120 `products.cost` and 35 of 492,226 `inventory_items.cost` values land on a different cent (all `6.644999999552965`, 6.64 vs 6.65). L9 differs from BigQuery on 7 rows only, all `mart_customer_summary.average_order_value` rows on which L2 already equals BigQuery: DuckDB divides `DECIMAL / BIGINT` in DOUBLE, BigQuery's `NUMERIC / INT64` rounds the quotient to nine decimals first. So the one-line `decimal(38,9)` change removes all 273,826 cent differences but would create those 7 (proposal in `rows.md`). **Applied on 2026-10-07, together with `money_quotient()`, which divides exactly; see the row above.** |
| **Source drift: the of-record pair cannot be joined row by row** | `bigquery-public-data.thelook_ecommerce` grew between the of-record load (2026-09-27T19:31:51Z) and the fresh one (2026-09-28T05:52:29Z). The of-record BigQuery tables are frozen at the old rows; its views, and any new DuckDB load, read the new ones. | `inventory_items` 489,625 → 492,226 (+2,601), `orders` 124,952 → 125,545 (+593), `order_items` 181,313 → 182,483 (+1,170), `events` 2,425,698 → 2,436,872 (+11,174); `products`, `users`, `distribution_centers` keep their row counts (`users` bytes 19,818,028 → 19,816,148). Recomputed on 2026-09-28, 57 of 99 of-record BigQuery values reproduce (every miss is a view) and 9 of 99 of-record DuckDB values reproduce on today's `dev.duckdb`. Every published figure of `results.md` stays as measured; a row-level comparison needs a pair built from one load, as `fresh/` is. |
| **One dataset, one run, one box** | One of-record run of each build, one dataset (`thelook_ecommerce`), 3 CPUs. The two probe logs were recorded 12-14 minutes before the of-record run, against the previous run's report (same 55 differing columns). | Durations are single runs: DuckDB 19.96 s and BigQuery 230.25 s of dbt model time (11.5x; per model 3.1x to 62.0x). |
| **The fixture's schema is a subset of the real one** | **Closed** (card t_153b4307, 2026-10-07). Historically measured by the loader: the real tables carry `users.user_geom` and `distribution_centers.distribution_center_geom` (`GEOGRAPHY` on BigQuery, `GEOMETRY` once loaded into DuckDB), which the fixture lacked; staging selects named columns, so they were inert. The fixture now carries both columns, last in each table, as DuckDB's native `GEOMETRY` (a WKT `POINT(longitude latitude)` from the row's own lat/lon); the mapping has a seam macro, `geography_type()` (`macros/polyglot/types.sql`), and both columns are declared in the source yml. `scripts/check_source_schema.py` (`make check-schema`, a step of `make pre-pr`) proves on every run that fixture == declared == real (names, order, and the fixture's types through one explicit mapping) and binds every source-reading model against the fixture, so a model that reads a real column the fixture lacks is a finding; `--demo` shows it fail on such a model, then pass. | Was 2 columns, nothing reading them. Now 0 differing columns: 7 tables, 75 columns on each side. The real side is `scripts/fixtures/real_schema.json`, a `tables.get` schema capture of the seven real tables (2026-10-07T09:23:53Z, 7 tables / 75 columns, column order as the table's; `python3 scripts/check_source_schema.py --emit` refreshes it, read-only metadata that bills nothing). It was first bootstrapped without a key from the real load's measured columns (`loader.log:26-101`) and then emitted; the two agree on every name, order and type. |
| **The real dataset's value distributions** | The fixture's rows are invented, and every revenue figure in `README.md` comes from the fixture. | Row counts and test outcomes on the real data are measured. Distributions are unverified. |
| **`products.cost` rounding** | Measured, and left as is by decision. | 7,923 of 29,120 real rows (27%) are off by half a cent or more, so the `money_type()` cast rounds real costs by up to half a cent — on DuckDB only; BigQuery's `numeric` keeps the sub-cent digits, which is the money difference in the first row. |
| **`inventory_items.cost` = `products.cost`**, and the denormalised price and centre | Holds on the fixture (0 differences). The rounding measurement did not test this equality. | One unverified assumption about the real data. |
| **The real data through the fixture's eyes** | The coherence checks of `scripts/load_duckdb_sources.sh` (orphans, ordering, `num_of_item`) were not run against the real load; the real load checks row counts and timestamps only. | Unverified on the DuckDB copy; the corresponding real-data facts were measured on BigQuery (`README.md`, "Assumptions the measurement settled"). |

## 2. The BigQuery write path

| gap | why | size |
|---|---|---|
| **`maximum_bytes_billed` enforcement** | Measured (2026-10-06, card t_fc6d405f): with a 1000-byte ceiling the ceiling **has** refused a query, `HTTP 400 ... {"reason": "bytesBilledLimitExceeded", "message": "Query exceeded limit for bytes billed: 1000. 141557760 or higher required."}`; a job refused this way bills nothing. The build is now priced: 1,323,806,504 bytes processed, 4,653,580,288 billed (the 10 MB per-query minimum dominates 167 tiny test jobs); the largest single job processed 150,593,696 bytes. | Closed as a control. The ceiling is per job (1,000,000,000 bytes), and **0** of the build's jobs come near it, so at the configured 1 GB it has still never refused a build job. |
| **Partitioning and clustering** | Measured (2026-10-07, card t_55f119de) on one table, `fct_inventory_items`, the largest fact table (488,895 rows, 49,525,078 bytes), in `coreychimpbot.experiments_partition`. Keys from the seam `physical_layout()` (`macros/polyglot/physical.sql`): partition by day on `created_at` (`timestamp`), cluster by `product_id`; DuckDB's branch is empty. `tables.get` reports `timePartitioning type=DAY field=created_at` and clustering `product_id` (before: none, none); `INFORMATION_SCHEMA.PARTITIONS` lists **2,826** day partitions, `20181121` to `20261010`, holding all 488,895 rows. The representative query, `SELECT *` over one month of `created_at` (`2024-06`, 30 partitions, 5,841 rows), uncached: processed 49,525,078 → 592,415 (**-98.8 %**), billed 50,331,648 → 10,485,760 (**-79.2 %**; the after figure is the 10 MiB per-query minimum). The unfiltered `full_scan` control is identical in both legs. | Partition pruning measured, for one table and one query shape. **Clustering's own byte effect is unverified**: no measured query filters on `product_id` alone, and on a table this size partition pruning leaves nothing for clustering to prune; only the metadata and a green build establish it. The before leg is a scratch copy, not a build of record. |
| **DDL beyond a plain build** | The 29 models were materialised, with 195 of 196 tests passing and 1 intended warning (orchestrator's `make bq`, 2026-09-27; again 2026-10-06, `196 total \| 195 success \| 1 warn`); with 30 models, `DBT_ENV=partition make bq` exits 0 with `198 total \| 197 success \| 1 warn` (2026-10-07). Table options are now exercised: partitioning and clustering on one mart (row above). Incremental models and concurrency were not tested. | Table options: one mart, built and measured. Incremental models, concurrency and every other DDL option remain unverified. |
| **The preflight's refusal path** | `scripts/bq_preflight.py` (run by `make bq`) names the missing permission and prints the two `gcloud` grants. Its 403 branches (`datasets.insert`, `jobs.query`, `tables.list`) have not been exercised on a machine that genuinely lacks the permission: this account holds every one. Only the missing-dataset path ran (`--dataset experiments_does_not_exist`, exit 2, `--create` not passed). The historical 403 for `bigquery.datasets.create` predates the script. | Unverified, not broken: 3 refusal branches never ran; `--create` creating a dataset never ran either (the target already exists). |

## 3. The macro layer

| gap | why | size |
|---|---|---|
| **Macros used by no model** | `polyglot_render --target bigquery` and the guardrail inspect rendered text only. The 9 dialect macros that no model calls directly were never executed on BigQuery (`safe_cast`, `to_string`, `format_date_str`, `timestamp_trunc_to`, `except_columns`, `regexp_contains`, `decimal_type`, `type_bigint_array`, `geography_type`). | 9 of 28 dialect macros have an unexecuted BigQuery branch (re-measured 2026-10-07, after `physical_layout`, `mart_polyglot_types` and `geography_type`; it was 10 of 26). The 19 that models call have run on BigQuery (the 30-model `make bq`, 2026-10-07). |
| **The BigQuery half of `make portability` / `make polyglot`** | The self-check prints `selfcheck skipped: bigquery cannot be executed here (no credentials; render-only)` and exits 0 by design. | `make polyglot` proves the DuckDB half only: 44 cases. |
| **`generate_date_series` month steps on BigQuery** | DuckDB drifts from a month-end start (measured, [`challenges.md`](challenges.md) 3.3). No BigQuery query with that shape was run. | One documented case. The only model that uses the macro, `dim_date`, steps by day. |
| **`decimal_type`'s BigQuery branch** | `numeric` for `p <= 38, s <= 9` comes from BigQuery's documentation, not from a measurement. | One rule, unexecuted. No model calls `decimal_type`. |
| **The guardrail is a blacklist** | It fails on 15 BigQuery-only and 13 DuckDB-only tokens. A construct outside those lists passes silently. | `PORTABLE` means none of those 28 tokens appears. It does not prove equivalence. |
| **Array/struct/JSON rendering in the parity harness** | The harness can render these types, but no model has such a column. | Implemented, never exercised. |
| **The macro layer on a project without this seam** | `move_to_duckdb.py` exits 2 without `macros/polyglot`. The manual checklist has not been run on another project. | One project only. |

## 4. Tests

| gap | why | size |
|---|---|---|
| **The singular tests' failing path, on the fixture** | The three strict tests return zero rows on the fixture, and none was run against an injected violation. The loader's own exit-1 path was refused by the session's permissions in card 2. | 3 strict singular tests plus the loader's failure branch are unverified. The fourth test (`severity: warn`) does fire on the real data, with 137,795 rows. |

## 5. Transport A (the extension)

| gap | why | size |
|---|---|---|
| **Other dataset shapes** | Only `usa_names`, `thelook_ecommerce` and one `GEOGRAPHY` table were read. There was no partitioned, clustered or external table, and no view read through the catalog. | Characterised for one shape. |
| **Parallelism** | The box has 3 CPUs and each run was single. Timings vary by ±50% between runs. | "No win from more streams" holds for this box only. |
| **Bulk or concurrent writes** | Only one `CREATE`/`INSERT`/`DROP` round trip was measured. | Writes are barely characterised (insert 5.6 s to 128.7 s). |
| **The extension against the source's timestamp contract** | The source definition declares timestamps as absolute instants, `TIMESTAMPTZ` on DuckDB (`models/staging/_thelook__sources.yml:16`), and `default__to_utc_timestamp` casts through `timestamptz` (`macros/polyglot/casting.sql:49-51`). The extension returns a BigQuery `TIMESTAMP` as zone-less `TIMESTAMP` (`analyses/transport_a/README.md:179`). Measured on the real tables with `--raw-timestamps` (session `Europe/Vienna`): **every one of the 12 timestamp columns is shifted on 100% of its non-null rows, by -1 or -2 hours** (e.g. `orders.created_at` `2019-01-15 07:03:47` → `2019-01-15 06:03:47`; `events.created_at` `2019-01-02 00:20:00` → `2019-01-01 23:20:00`, across a date boundary). | Closed for this project's DuckDB leg: `scripts/load_duckdb_real_sources.sh` delivers every timestamp as `TIMESTAMPTZ` and proves row by row that 0 instants moved. Open for anyone else reading BigQuery through the extension: the mapping is the loader's, not the extension's. Only `Europe/Vienna` was measured on the real tables. |

## 6. Transport B (files)

| gap | why | size |
|---|---|---|
| **HMAC-key reads (`gs://`, `TYPE gcs`)** | The box has no HMAC keys. Those reads were exercised only as failures (b06, b06b). | The route the card named is unverified. The bearer-token route is measured instead. |
| **The 1 GiB per-file cap** | Shard size follows input parallelism (~1 M rows per file). The largest file seen was 27,112,967 bytes, from an 8.0 GB table. | Documented, never hit. |
| **Parallel reads of many objects** | b09 is one DuckDB process reading 59 objects (20.73 s in the run of record, 27.14 s cited in the README's gap list). | Neither a distributed reader nor tuned parallelism was tested. |
| **BIGNUMERIC beyond 16 digits in files** | The narrowing to `double` is measured. No other export format was tried. | AVRO was not tested, so whether any export option avoids the narrowing is unknown. |
| **A cross-location bucket** | The bucket and the dataset are both `US`. The failure is recorded on the t_2e263433 card thread (board, not in the repo). | Not re-measured in a scenario. |

## 7. The two-repo fallback

| gap | why | size |
|---|---|---|
| **Two-repo drift frequency** | No two-repo setup was run over time. | Argued from this repo's history (the 1/29 type divergence), not measured. |
| **The moved project standalone** | Its profile points at the source repo's `dev.duckdb` by absolute path. | Unverified. It needs `path` and `DBT` edited. |

## 8. dbt v2 itself

| gap | why | size |
|---|---|---|
| **The `MacroSyntaxInvalid (dbt1502)` warning** | It was recorded once, for `analyses/move_to_duckdb/README.md:235:54` (the orchestrator's record, not a file here). On 2026-09-27 the orchestrator probed with a `.md` under `analyses/` containing `{{ config(...) }}` and `{% set x = ... %}`, through `dbt parse` and `dbt compile`, and it did not warn. | Recorded, not reproduced. The trigger is unknown. |

## 9. The documentation itself

| gap | why | size |
|---|---|---|
| **`README.md`'s BigQuery status was stale** | The `### bigquery` section said the target "has **never been connected**". The first bullet of "What is NOT verified" said it "has still never been *materialised*" and that `make bq` "still exits non-zero". Both were true before the grants landed on 2026-09-27. They were false afterwards, when `make bq` built all 29 models (`196 total \| 195 success \| 1 warn`). The target table in the same file already said the opposite. | **Fixed with this document** (those two paragraphs only). |
| **Other stale numbers left in `README.md`** | The status paragraph still says BigQuery "never runs there". "The models" and "What is verified" say `168 tests` / `197 total` (card-3 era). Today's `make duck` prints `167 tests` / `196 total`, because the boolean `accepted_values` test was removed ([`challenges.md`](challenges.md) 5.2). | **Fixed** by card `t_c495bfea` (2026-09-27): the status paragraph, the test counts and `SPEC.md`'s superseded line were corrected. |
| **Transport B's b07c/b07d status code** | `analyses/transport_b/README.md:60` says the no-secret and bogus-token controls fail with 403. The logs show `(HTTP 0 Internal Server Error)` (`b07c.log:16`, `b07d.log:19`). | The conclusion (the controls fail) holds. The status code in the README is wrong. |

## 10. CI

| gap | why | size |
|---|---|---|
| **CI's BigQuery leg** | CI runs `make ci-compile` in two jobs ([`ci.md`](ci.md)). The gate, `ci-compile`, deliberately holds no credential: it compiles DuckDB and runs the guardrail, and maps the script's exit 2 (BigQuery `n/a`) to green with a `::warning` and a job-summary line. The BigQuery leg, `ci-compile-bigquery`, runs only when the `BQ_SA_KEY` repository secret exists, and the token that built the workflow could not create repository secrets, so **until the secret is added that job is skipped and no run speaks to the BigQuery target**. Under the earlier one-job workflow the same absence made the job red (runs 36598771536, 36599048212, 36599339715, the last on `main`); a red job now means a real finding. | Unverified in CI, not broken: the DuckDB compile and the guardrail run and pass. With the secret, the leg proves the project renders for BigQuery with a service-account-shaped key: not a live connection, not a build. `dbt compile` bills nothing on DuckDB, and on BigQuery it issued no query in the measured no-credential case (it exited 0 with no credentials at all). CI builds and queries neither target. |
| **CI does not validate SQL** | Measured on 2026-09-29 with a deliberately broken model. The bad `ref('no_such_model')` was caught by the compile (`DependencyNotFound (dbt1048)`). The raw syntax error `select (( from ...` was not: it compiled (`258 total \| 258 success`) and was written to `target/compiled/` verbatim. A `try_cast` plus a `target.type` branch compiled on both engines, and the guardrail caught it (`NOT PORTABLE: 2 finding(s)`). The DuckDB leg does fail end to end: `FAIL ... (exit 1)`, script exit 1. | By design, not fixed: a green `dbt compile` means "renders for both engines, no dialect leaked", not "the SQL is valid"; `dbt compile` renders, it does not parse the SQL. Only running the models (`make duck`, `make bq`) would catch a syntax error, and CI runs neither. |

## Where each claim comes from

| gap | source |
|---|---|
| value parity: 29/29 row counts, 8/29 match, marts 1/11, 21 differ | `analyses/value_parity/results.md:11-12` and per-model table; `analyses/value_parity/logs/parity.log:14-44` (the verdict line is `:44`, `parity: MISMATCH. gating: none; value/row: [...21 models...]; not measured: none`) |
| value parity method, both builds green, self-check, baseline | `analyses/value_parity/results.md:3-17`; `analyses/value_parity/logs/parity.log:5,11`; `analyses/value_parity/logs/dbt_build_duckdb.log:207`, `dbt_build_bigquery.log:207` |
| 55 columns, all money but one; 0 row-count / null-count differences | `analyses/value_parity/results.json` (every `differences` entry: 55 columns, checks `column_checksum` ×55 and `column_distinct_count` ×44 only) |
| money cause: `decimal(18,2)` vs `numeric`, 29,035 of 29,120 not whole cents | `macros/polyglot/types.sql:85-91`; `analyses/value_parity/logs/probe_decimal_text.log:8,11` |
| 23 reconcile at 2 decimals, 32 do not | `analyses/value_parity/logs/probe_scale_attribution.log:59` |
| `gross_margin_rate` 18,699 vs 328 distinct | `analyses/value_parity/results.md:236`; raw ratios 328 vs 18,723 at cents, `analyses/value_parity/logs/probe_decimal_text.log:15` |
| one-row double rounding, `6.644999999552965` | `analyses/value_parity/logs/probe_decimal_text.log:13`; on the fresh load, `analyses/value_parity/rows.md:1015,1018` (1 of 29,120 `products.cost`, 35 of 492,226 `inventory_items.cost`) |
| fresh pair: 8/29, marts 1/11, rows equal, `int_order_items__enriched` not_measured | `analyses/value_parity/fresh/results.md:11-12,37,137-140` |
| row join: C = 0, buckets, keys, NULLs, gates | `analyses/value_parity/rows.md:7-13,51-67,114`; `analyses/value_parity/rows.json`; `analyses/value_parity/logs/rows/run.log`, `gates.log`, `pull.log`, `<model>.log` |
| per-column delta ranges, 23 columns without a cent difference | `analyses/value_parity/rows.md:118-176` (per-column summary) |
| L9 off on 7 `average_order_value` rows, division typing | `analyses/value_parity/rows.md:993-1007`; `models/marts/mart_customer_summary.sql:39-40` |
| source drift, row and byte counts | `analyses/value_parity/logs/loader.log:1,8-14`; `analyses/value_parity/logs/row_join_loader.log:1,8-14`; `analyses/value_parity/rows.md:19-49` |
| of-record values today: 57/99 BigQuery, 9/99 DuckDB | `analyses/value_parity/logs/rows/of_record_gate.log` |
| durations 19.96 s / 230.25 s, 3.1x-62.0x | `analyses/value_parity/results.md:52`; `analyses/value_parity/logs/parity.log:14,42` |
| probe timing vs the of-record run | `analyses/value_parity/logs/probe_scale_attribution.log:2` (`2026-09-27T19:17:58Z`), `probe_decimal_text.log:2` (`19:19:36Z`), `loader.log:1` (`19:31:51Z`) |
| fixture schema a subset (two `GEOMETRY` columns), historical | `analyses/value_parity/logs/loader.log:103-106` |
| fixture schema closed: the two columns, the seam type, the declared contract | `scripts/fixtures/thelook_ecommerce.sql` (`distribution_centers`, `users`); `macros/polyglot/types.sql` (`geography_type`); `models/staging/_thelook__sources.yml` |
| the real-schema record | `scripts/fixtures/real_schema.json` (provenance in the file: `tables.get` capture 2026-10-07T09:23:53Z; first bootstrapped from `analyses/value_parity/logs/loader.log:26-101` and then emitted — the two agree on every name, order and type; `python3 scripts/check_source_schema.py --emit` refreshes it) |
| fixture == declared == real, models bind: 7 tables, 75 columns, arms A-D 0 findings | `scripts/check_source_schema.py`; `make check-schema`; step 4 of `scripts/pre_pr.sh`; `NOTES.md`, section "Card t_153b4307" |
| the check can fail: `--demo` | `python3 scripts/check_source_schema.py --demo` (a temporary `models/staging/_schema_demo.sql` reading `user_geom_wkt`: `FIXTURE SCHEMA: 1 finding(s)`, then `FIXTURE SCHEMA OK`); `NOTES.md`, section "Card t_153b4307" |
| surrogate keys agree | key columns at `models/intermediate/int_inventory__by_product_center.sql:19`, `models/intermediate/int_cohorts__user_months.sql:36-37`, `models/marts/mart_cohort_retention.sql:34-35`; none of them in `analyses/value_parity/results.md` "Differences, in full" |
| fixture path still 28/29 differ, 1/29 match | `README.md:761-770`; `NOTES.md:1197-1203,1236-1238` |
| real distributions, `products.cost` 27%, cost equality | `README.md:709-726`; `NOTES.md:904-906,925-935` |
| real load has no coherence checks | `scripts/load_duckdb_real_sources.sh:26-28` (what it checks); `scripts/load_duckdb_sources.sh:48-139` (the fixture's checks); `README.md:727-734` (the facts measured on BigQuery) |
| `maximum_bytes_billed` | `README.md:399-405,679-688,825-827`; `NOTES.md:1229-1231`; refused query, build price and largest job: `NOTES.md`, section "Card t_fc6d405f" (measured 2026-10-06 by the orchestrator, not in a log file) |
| preflight, its exit codes and its unexercised refusal branches | `scripts/bq_preflight.py` (header); `scripts/run_bq.sh` (header); `NOTES.md`, section "Card t_fc6d405f" (the commands run and their output) |
| partitioning/clustering: bytes processed and billed, metadata, 2,826 partitions, 30 in `2024-06` with 5,841 rows, job ids | `analyses/partitioning/results.md`; `analyses/partitioning/results.before.json`, `results.after.json`; `analyses/partitioning/logs/before.log`, `after.log`; method `analyses/partitioning/README.md`; `NOTES.md`, section "Card t_55f119de" |
| largest fact table (488,895 / 49,525,078 vs 181,070 / 45,581,586) | `analyses/partitioning/README.md`, "Why this table" (BigQuery table metadata, 2026-10-07) |
| the seam keeps the partitioned model portable; `make portability` 0/15, 0/13, 0 findings, 31 files; `198 total` on both legs | `macros/polyglot/physical.sql`; `models/marts/fct_inventory_items.sql`; `docs/move_to_duckdb.md` §5; `NOTES.md`, section "Card t_55f119de" (orchestrator's `make portability`, `DBT_ENV=partition make bq` and `dbt build --target duckdb`, 2026-10-07, not in a log file) |
| DDL | `NOTES.md:1229-1231`; `docs/move_to_duckdb.md:209-222`; orchestrator's `make bq` (2026-09-27) |
| 9 of 28 macros not called by a model (was 10 of 26) | method: `docs/move_to_duckdb.md:98-116`, the counting script in [`challenges.md`](challenges.md) "The verdict"; re-run 2026-10-07 with `move_to_duckdb.Seam` over `models/` (`model files 30 call sites 150`, `dialect macros 28 called by a model 19`, `not called by any model: [... 'geography_type'] 9`, `branch macros 56`); the 30-model build, `NOTES.md`, section "Card t_55f119de" |
| render-only BigQuery half | `README.md:689-708`; `NOTES.md:1067-1083` |
| month steps | `macros/polyglot/arrays.sql:57-60`; `NOTES.md:1079-1081` |
| `decimal_type` BigQuery rule | `NOTES.md:1074-1078` |
| blacklist guardrail | `README.md:699-705` |
| array/struct/JSON in the harness | `NOTES.md:1176-1177,1234-1235` |
| no other project | `docs/move_to_duckdb.md:549-551` |
| singular tests' failing path, loader's exit 1 | `README.md:776-780`; `NOTES.md:269-276,709-710` |
| Transport A limits | `analyses/transport_a/README.md:314-327` |
| extension vs the timestamp contract | `models/staging/_thelook__sources.yml:16`; `macros/polyglot/casting.sql:49-51`; `analyses/transport_a/README.md:179,188-192`; the shift on the real tables, `analyses/value_parity/logs/loader-raw-timestamps.log:120-133` (e.g. `:129`, `orders created_at ... 124952 124952 [-2.0, -1.0] 2019-01-15 07:03:47 2019-01-15 06:03:47`); the mapped load, `analyses/value_parity/logs/loader.log:16-24` (`moved` 0) and `:108-121` (0 shifted); earlier synthetic check `duckdb -c "set timezone='America/Los_Angeles'; ..."` (this worktree, 2026-09-27); `NOTES.md:949-951` |
| Transport B gaps | `analyses/transport_b/README.md:283-303`; `analyses/transport_b/README.md:91` (27,112,967 bytes) |
| drift, standalone move | `docs/move_to_duckdb.md:560-572` |
| `MacroSyntaxInvalid` | orchestrator's record and probe (2026-09-27, not in a file); `history/.cc-move-run3.json` |
| stale README paragraphs | `README.md` before this edit (`### bigquery`, first "What is NOT verified" bullet); `README.md:371` target table; `scripts/run_bq.sh:13-21`; orchestrator's `make bq` |
| 168 vs 167 tests | `README.md:13,136,511-512,526-527`; orchestrator's `make duck` (`Processed: 29 models \| 167 tests`) |
| b07c/b07d status | `analyses/transport_b/README.md:60`; `analyses/transport_b/logs/b07c.log:16`, `b07d.log:19` |
| card-thread facts | t_2e263433 card thread (board, not in the repo); `analyses/transport_b/README.md:295-297` |
| CI's BigQuery leg `n/a` in the gate, skipped without the secret; compile needs no credential | `scripts/ci_compile_both.sh` (header and the credential gate); `.github/workflows/1_dbt_bigquery_duckdb.yml`, formerly `ci.yml` (jobs `ci-compile` and `ci-compile-bigquery`); [`ci.md`](ci.md); the red one-job runs 36598771536, 36599048212, 36599339715 (GitHub Actions run ids); `.venv/bin/dbt compile --target bigquery` exiting 0 with no credential (2026-09-29, `Summary: 257 total \| 257 success`) |
| CI does not validate SQL; guardrail and bad `ref()` caught | orchestrator's `make ci-compile` runs with a temporary `models/intermediate/_ci_break.sql`, removed again (2026-09-29, not in a file) |
