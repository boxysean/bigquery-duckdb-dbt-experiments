# Gaps: what could not be established here, and why

**The largest gap is cross-engine value parity.** The two targets read different data by
design, so rows and values are compared for 1 model in 29. The next largest is the BigQuery
write path beyond a plain build: it now materialises all 29 models, but the cost ceiling
has never been hit, and no partitioning or clustering is used. Most of the other gaps are
documented limits that were never reached, not failures.

Two words are used deliberately below:

* **Unverified** means nothing was run that could fail. It does not mean broken.
* **Broken** means a run failed. No gap listed here is broken, except where a measured
  failure is quoted.

Related documents: [`challenges.md`](challenges.md) covers what was hit, and
[`move_to_duckdb.md`](move_to_duckdb.md) §9 covers the fallback's own gaps. The table at the
end maps every gap to its source.

## 1. The two targets read different data

| gap | why it could not be established | size |
|---|---|---|
| **Cross-engine value parity** | DuckDB reads the generated fixture and BigQuery reads `bigquery-public-data`. The harness can gate on values with `--same-data`, but no run has had both targets on one dataset. | 28 of 29 models differ on rows and checksums. **1 of 29** (`stg_thelook__distribution_centers`) matches on everything. Schema and type parity is measured (0 gating mismatches); value parity is unverified. |
| **The real dataset's value distributions** | The fixture's rows are invented, and every revenue figure in `README.md` comes from the fixture. | Row counts and test outcomes on the real data are measured. Distributions are unverified. |
| **`products.cost` rounding** | Measured, and left as is by decision. | 7,923 of 29,120 real rows (27%) are off by half a cent or more, so the `money_type()` cast rounds real costs by up to half a cent. This is a known, bounded effect, not an unknown one. |
| **`inventory_items.cost` = `products.cost`**, and the denormalised price and centre | Holds on the fixture (0 differences). The rounding measurement did not test this equality. | One unverified assumption about the real data. |
| **Surrogate-key values across engines** | Both branches hash the same `'||'`-joined integer text by construction, and both have run. The keys differ wherever the rows differ, which is everywhere except the distribution centres. | Unverified until value parity is (above). |

## 2. The BigQuery write path

| gap | why | size |
|---|---|---|
| **`maximum_bytes_billed` enforcement** | The v2 adapter accepts the setting, and `dbt debug` echoes `1000000000`. No query came near 1 GB, so the ceiling has never refused anything. | One named, unverified control. The full build has not been priced against it either. |
| **Partitioning and clustering** | The warehouse uses neither, so nothing has exercised them. | Unverified. In the one-project design they are on the "cannot move" list (`docs/move_to_duckdb.md` §5). |
| **DDL beyond a plain build** | The 29 models were materialised once, with 195 of 196 tests passing and 1 intended warning (orchestrator's `make bq`, 2026-09-27). Nothing about table options, incremental models or concurrency was tested. | The leg is materialised. Everything beyond a plain view/table build is unverified. |

## 3. The macro layer

| gap | why | size |
|---|---|---|
| **Macros used by no model** | `polyglot_render --target bigquery` and the guardrail inspect rendered text only. The 10 dialect macros that no model calls directly were never executed on BigQuery. | 10 of 26 dialect macros have an unexecuted BigQuery branch. The 16 that models call have run on BigQuery. |
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
| **The time-zone path on real data** | SPEC and the fixture assume a BigQuery `TIMESTAMP` reaches DuckDB as `TIMESTAMPTZ` (`NOTES.md:949-951`). Transport A measured the opposite: it arrives as zone-less `TIMESTAMP` (`analyses/transport_a/README.md:188-192`). With `set timezone='America/Los_Angeles'`, the macro's DuckDB branch `timezone('UTC', cast(x as timestamptz))` turned the naive `2024-01-02 03:04:05` into `2024-01-02 11:04:05` (`duckdb -c`, this worktree, 2026-09-27). | Measured risk on a path that has never run. No model reads BigQuery through the extension today, so nothing is broken. If the DuckDB leg is pointed at the real tables that way, `to_utc_timestamp` would shift every `*_at` column by the session offset. |

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
| **Card-thread evidence** | The GCS location error, the `storage.buckets.get` 403 and the missing `bigquery.datasets.create` grant are on the t_2e263433 board thread, which is not in this repository. | Three facts in [`challenges.md`](challenges.md) 6.1 cannot be checked from the repo. |

## Where each claim comes from

| gap | source |
|---|---|
| value parity, 28/29 differ, 1/29 match | `README.md:687-715`; `NOTES.md:1197-1203,1236-1238` |
| real distributions, `products.cost` 27%, cost equality | `README.md:662-678`; `NOTES.md:904-906,925-935` |
| surrogate-key values | `README.md:716-720` |
| `maximum_bytes_billed` | `README.md:370-374,770-772`; `NOTES.md:1229-1231` |
| partitioning/clustering, DDL | `NOTES.md:1229-1231`; `docs/move_to_duckdb.md:209-222`; orchestrator's `make bq` (2026-09-27) |
| 10 macros not called by a model | `docs/move_to_duckdb.md:98-116`; the counting script in [`challenges.md`](challenges.md) "The verdict" |
| render-only BigQuery half | `README.md:642-661`; `NOTES.md:1067-1083` |
| month steps | `macros/polyglot/arrays.sql:57-60`; `NOTES.md:1079-1081` |
| `decimal_type` BigQuery rule | `NOTES.md:1074-1078` |
| blacklist guardrail | `README.md:652-658` |
| array/struct/JSON in the harness | `NOTES.md:1176-1177,1234-1235` |
| no other project | `docs/move_to_duckdb.md:549-551` |
| singular tests' failing path, loader's exit 1 | `README.md:721-725`; `NOTES.md:269-276,709-710` |
| Transport A limits | `analyses/transport_a/README.md:314-327` |
| time-zone path | `NOTES.md:949-951`; `analyses/transport_a/README.md:179,188-192`; `duckdb -c "set timezone='America/Los_Angeles'; select timezone('UTC', cast(timestamp '2024-01-02 03:04:05' as timestamptz)) ..."` (this worktree, 2026-09-27) |
| Transport B gaps | `analyses/transport_b/README.md:283-303`; `analyses/transport_b/README.md:91` (27,112,967 bytes) |
| drift, standalone move | `docs/move_to_duckdb.md:560-572` |
| `MacroSyntaxInvalid` | orchestrator's record and probe (2026-09-27, not in a file); `.cc-move-run3.json` |
| stale README paragraphs | `README.md` before this edit (`### bigquery`, first "What is NOT verified" bullet); `README.md:339` target table; `scripts/run_bq.sh:13-21`; orchestrator's `make bq` |
| 168 vs 167 tests | `README.md:13,16,104,471-472,484-490`; orchestrator's `make duck` (`Processed: 29 models \| 167 tests`) |
| b07c/b07d status | `analyses/transport_b/README.md:60`; `analyses/transport_b/logs/b07c.log:16`, `b07d.log:19` |
| card-thread facts | t_2e263433 card thread (board, not in the repo); `analyses/transport_b/README.md:295-297` |
