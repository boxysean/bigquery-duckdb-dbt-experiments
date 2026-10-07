# BigQuery → Spark: the incompatibility catalogue

What it took to run one dbt project, unchanged in intent, on both **BigQuery** and **Spark
4.2.0**, construct by construct. This is the deliverable of the `bigquery_spark/` project.

**How to read a row.** Every cell in the BigQuery and Spark columns is either what the engine
actually answered or raised when probed on this box, or a reference to the macro that handles
it (`macros/polyglot/<file>.sql:<lines>`). Nothing here is a prediction. Where a probe was not
made, or was not a fair equivalent, the cell says **unverified** and why.

Sources of the measurements:

* **Construct probes**: `NOTES.md` §2, §6 and §10. One probe per construct against the live
  Spark 4.2.0 Thrift Server (beeline, `jdbc:hive2://127.0.0.1:10000`) and the BigQuery REST API
  (no table reads, 0 bytes billed), 2026-10-06.
* **Builds and value parity**: this run, 2026-10-07 CEST. `dbt build` on both targets, and
  `scripts/parity.py --same-data` over all 29 models on the same real rows
  (`parity-report.md`, generated 2026-10-07T01:20:48+0200).
* **"Used by"**: a scan of every `models/**/*.sql` (`NOTES.md` §10, macro map), rechecked
  with a grep of the model tree for this document.

---

## 1. The headline numbers

| | |
|---|---|
| Models | **29** (7 staging, 11 intermediate, 11 marts), plus 167 tests and 1 analysis |
| Render for both targets | **29 of 29** (`check_portability.py`: 30 compiled files, 0/13 BigQuery-only tokens in the Spark render, 0/12 Spark-only tokens in the BigQuery render, 0 target branches: `PORTABLE`) |
| Executed on Spark | **29 of 29**: `dbt build --target spark` exit 0, *29 models \| 167 tests \| 196 total: 195 success, 1 warn* |
| Executed on BigQuery | **29 of 29**: `dbt build --target bigquery` exit 0, the same numbers |
| Model SQL unchanged from the BigQuery original | **28 of 29**; the one rewrite is `dim_date.sql` (`UNNEST` → `explode_array_rows`) |
| Same values on both engines | **8 of 29** match on every check; **21 differ on values only** (money columns); **0** differ on column names or types |
| Sources | 7 of 7 identical on every check (Spark reads a Parquet snapshot pulled from BigQuery; BigQuery reads `bigquery-public-data.thelook_ecommerce` live) |

The one warn is `tests/assert_order_item_created_at_is_plausible`, which is `severity: warn`
by design (the published dataset's timestamp jitter) and warns identically on both engines.

---

## 2. The catalogue

### 2.1 Works unchanged: the same SQL on both engines

These needed no change at all. They are here because a catalogue of only the problems
misrepresents the difficulty: most of standard analytic SQL moved across as-is.

| Construct | BigQuery | Spark | Handled by | Notes / residual risk |
|---|---|---|---|---|
| `QUALIFY row_number() over (order by a) = 1` | `1 2` (works) | `1 2`: works unchanged on 4.2 | nothing: same SQL | Not used by any model (no `qualify` in the tree). Older Spark versions are not covered by this measurement. |
| `SELECT * EXCEPT (b)` | `1` | `1`: Spark 4.2 accepts the BigQuery spelling | `except_columns` renders `* except (...)` on both branches, `macros/polyglot/selection.sql:20-26` | The macro exists for symmetry only. Not called by any model. `* except (` is deliberately in neither token list of the guardrail. |
| `APPROX_COUNT_DISTINCT(x)` | `3` | `3` | nothing | Not used by any model. Only a small exact case was probed: whether the two approximations agree at scale is **unverified**. |
| `PIVOT (sum(v) for k in (...))` | `1 2` | `1 2` | nothing | Not used by any model. |
| Recursive CTE (`with recursive`) | `3` | `3` | nothing | Not used by any model. |
| `struct(1 AS a, 2 AS b).a` | `1` | `1` | `struct_literal`, identical branches, `macros/polyglot/structs.sql:23-37` | Not used by any model. |
| `EXTRACT(year/month/day FROM date)` | `2024` | `2024` | nothing; also inside `month_number`, `macros/polyglot/dates.sql:194-200` | Used unchanged in `dim_date.sql:26-28` and `mart_cohort_retention.sql:39-40`; `dim_date` matches on every parity check. `EXTRACT(week)` does **not** agree: see 2.3. |
| `ORDER BY x NULLS LAST` | `1` | `1` | nothing | |
| `7 / 2` | `3.5` | `3.5` | nothing | Neither engine does integer division with `/`. |
| `1 + 1.5` | `2.5` | `2.5` | nothing | |
| Window functions (`row_number() over (...)`) | executed in `dbt build` | executed in `dbt build` | nothing | Used in `int_events__sessions.sql:15`; that model (680,778 rows) matches on every parity check. |
| `md5(...)` surrogate keys | `to_hex(md5(concat(...)))` | `md5(concat_ws('\|\|', ...))`: `md5(concat_ws('\|\|', 1, 'x'))` = `df6729622b8fb993f31b1ba95a27e5cc` | `generate_surrogate_key`, `macros/polyglot/keys.sql:23-38` | Keys agree: parity joined `int_cohorts__user_months` (120,636 rows) and `mart_cohort_retention` (3,938) on their surrogate keys on both engines. Spark's `concat_ws` **skips** a NULL part (`md5(concat_ws('\|\|', 1, null))` = `md5('1')`); BigQuery's `concat` returns NULL. Inputs must be non-null. |
| `STRING` type, `TIMESTAMP` type names | `string`, `timestamp` | `string`, `timestamp` (typeof) | `string_type` / `timestamp_type`, `macros/polyglot/types.sql:34-40`, `:71-77` | `TIMESTAMP` means the same thing only because the Spark session is UTC: see the time-zone row in 2.3. |

### 2.2 A clean equivalent exists: a rename behind a macro

The behaviour matches; only the spelling differs. Each one costs a macro with two branches and
nothing else. The models call the macro and never see the dialect.

| Construct | BigQuery | Spark | Handled by | Notes / residual risk |
|---|---|---|---|---|
| `SAFE_CAST(x AS t)` | `SAFE_CAST('42' ...)` = `42` | `try_cast` = `42`; `try_cast('nope' as bigint)` = NULL; `safe_cast` raises PARSE_SYNTAX_ERROR | `safe_cast`, `macros/polyglot/casting.sql:12-18` | Not called by any model. |
| `SAFE_DIVIDE(n, d)` | `safe_divide` | `try_divide(1.0, 0.0)` = NULL, `try_divide(1.0, 4.0)` = 0.25; `safe_divide` → UNRESOLVED_ROUTINE | `safe_divide`, `macros/polyglot/math.sql:21-27` (casts both sides to `double`/`float64`) | Used by 3 models (`int_products__returns`, `mart_cohort_retention`, `mart_product_performance`). The macro returns a float on purpose; money averages use `round(x / nullif(y, 0), 2)` instead (`math.sql:12-15`). |
| `GENERATE_ARRAY(1, 4)` | sum of elements = `10` | `explode(sequence(1,4))` sum = `10` | `generate_series`, `macros/polyglot/arrays.sql:62-68` | **Behaviour differs when start > stop**: Spark `sequence(1, 0)` = `[1, 0]` (counts down) and `sequence(1, 0, 1)` raises `Illegal sequence boundaries`; BigQuery returns an empty array. Keep start ≤ stop. Used only by `analyses/polyglot_showcase.sql`. |
| `GENERATE_DATE_ARRAY(d, d, INTERVAL 1 DAY)` | `array_length` = 3 | `size(sequence(d, d, interval 1 day))` = 3; typeof `array<date>` | `generate_date_series`, `macros/polyglot/arrays.sql:93-103` | **Spark has no QUARTER interval**: `interval 1 quarter` is PARSE_SYNTAX_ERROR, so the Spark branch renders `interval 3n month` (`arrays.sql:94-97`). Month steps count from the start, no month-end drift (`2024-01-31` → `02-29`, `03-31`, `04-30`). Used by `dim_date.sql:18`. |
| `DATE_DIFF(later, earlier, DAY)` | `14` | `datediff(later, earlier)` = `14`; the BigQuery spelling raises UNRESOLVED_COLUMN | `date_diff_days`, `macros/polyglot/dates.sql:19-25` | Spark 4.2 also has its own `date_diff(end, start)` (measured: 4), a different signature, which is why the guardrail bans `date_diff(` in the Spark render. Used by `dim_date`. |
| `TIMESTAMP_DIFF(e, s, MICROSECOND)` (seconds between) | `timestamp_diff` | `unix_micros(e) - unix_micros(s)` = `90.5`; `unix_timestamp(e) - unix_timestamp(s)` = `90.0`: **drops sub-second precision** | `seconds_between`, `macros/polyglot/dates.sql:214-220` | The obvious Spark spelling (`unix_timestamp`) silently truncates. Used by `int_events__sessions` and `int_inventory_items__enriched`; `int_events__sessions` matches on every parity check. |
| `REGEXP_CONTAINS(x, p)` | `regexp_contains` | `regexp_like(x, p)` and `x rlike p` both work; `regexp_contains` → UNRESOLVED_ROUTINE | `regexp_contains`, `macros/polyglot/strings.sql:16-22` | Not called by any model. BigQuery uses RE2 and Spark `java.util.regex`; patterns outside the common subset (backreferences, lookaround) were **not probed: unverified**. |
| `EXTRACT(DAYOFWEEK)` as ISO day (Mon = 1) | `mod(extract(dayofweek ...) + 5, 7) + 1` | `(dayofweek(d) + 5) % 7 + 1`: Fri 5, Sun 7, Mon 1 | `day_of_week_iso`, `macros/polyglot/dates.sql:156-162` | Used by `dim_date`. |
| `PARSE_DATE('%Y-%m-%d', s)` | `2024-03-15` | `to_date(s, 'yyyy-MM-dd')` = `2024-03-15` | nothing (no macro) | Not used by any model. Same pattern-language difference as `FORMAT_DATE` (2.3): the format argument has to be rewritten, not just the function name. |
| `STRING_AGG(x, ',' ORDER BY x)` | `a,b,c` | `concat_ws(',', sort_array(collect_list(x)))` = `a,b,c` | nothing (no macro) | Not used by any model. The rewrite sorts the *aggregated values*; ordering by a different column (`ORDER BY y`) would need another construction, **unverified**. |
| `INT64` / `FLOAT64` | `int64`, `float64` | `bigint`, `double` (typeof); `float64` → UNSUPPORTED_DATATYPE | `int_type` / `float_type`, `macros/polyglot/types.sql:17-23`, `:50-56` | The most used seam: `int_type(` 51 calls in 19 files, `float_type(` 4 calls. |
| `ARRAY<INT64>` | `array<int64>` | `array<bigint>` (typeof); `array<int64>` → UNSUPPORTED_DATATYPE | `type_bigint_array`, `macros/polyglot/types.sql:156-162` | dbt-oss 2.0.5's Spark adapter **cannot fetch an array column** (`NotImplemented: [spark] Unsupported type ARRAY_TYPE`); no model returns one to the client. |

### 2.3 No clean equivalent: a rewrite, a behaviour change or a lost feature

| Construct | BigQuery | Spark | Handled by | Notes / residual risk |
|---|---|---|---|---|
| `UNNEST` in FROM (`cross join unnest(arr) as x`) | works | **UNRESOLVABLE_TABLE_VALUED_FUNCTION**: `Could not resolve unnest`; `lateral view explode(arr) v as x` works | `explode_array_rows` (a FROM-clause fragment), `macros/polyglot/arrays.sql:40-46` | **The one model rewrite**: `dim_date.sql:18`. A LATERAL VIEW needs a table alias as well as the column alias (`<alias>__arr`) and must follow a FROM item, so `from unnest(...)` alone becomes `from (select 1) {{ explode_array_rows(...) }}` (done in `analyses/polyglot_showcase.sql`). Both drop the outer row on an empty array (Spark `explode(array())` = 0 rows). `UNNEST ... WITH OFFSET` was **not probed: unverified**. |
| `SELECT * REPLACE (3 AS b)` | `1 3` | **PARSE_SYNTAX_ERROR** | nothing: no macro can express it | **No Spark spelling.** The workaround is writing the full column list, which loses the "every other column" behaviour: a new upstream column is silently dropped instead of passed through. Not used by any model. |
| Array `[OFFSET(0)]` | `10` | **PARSE_SYNTAX_ERROR** | nothing | Zero-based BigQuery indexing has no Spark syntax. Not used by any model. |
| Array `[ORDINAL(1)]` | `10` | **PARSE_SYNTAX_ERROR** | nothing | Not used by any model. |
| Array `[SAFE_OFFSET(5)]` | `None` (NULL, no error) | **PARSE_SYNTAX_ERROR** | nothing | What Spark's `element_at` returns for an out-of-range index was **not probed: unverified** (it may raise rather than return NULL). Not used by any model. |
| `element_at(arr, 1)` (Spark's indexer) | **Function not found** | `10`: **one-based** | nothing | **The silent off-by-one.** A BigQuery `arr[OFFSET(1)]` (second element) hand-translated to `element_at(arr, 1)` returns the *first* element: no error, wrong answer. The guardrail does not ban `element_at`. Not used by any model. |
| `TIMESTAMP_TRUNC(ts, HOUR)` | `1.7105076E9` (works) | **UNRESOLVED_ROUTINE**: no `timestamp_trunc`; the Spark form is `date_trunc('hour', ts)` (part first, quoted) | `timestamp_trunc_to`, `macros/polyglot/dates.sql:136-142` | Argument order and part syntax both change. Weeks: Spark `date_trunc('week', ...)` is already Monday (`2024-03-15 13:45:12` → `2024-03-11`); BigQuery's bare `WEEK` is Sunday, so the BigQuery branch renders `week(monday)` (`dates.sql:141`). |
| `DATE_TRUNC(date, MONTH)` | `2024-03-01`: a **DATE** | `date_trunc('month', d)` = `2024-03-01 00:00:00.0`: a **TIMESTAMP** | `month_start` returns a timestamp on both, `macros/polyglot/dates.sql:175-181` | A hand translation changes the column's type (DATE → TIMESTAMP) unless cast back. Used by 4 models via `month_start`. |
| `EXTRACT(week FROM date '2024-03-15')` | **`10`** | **`11`** | nothing: no macro | **Silent divergence**, no error on either side (BigQuery's Sunday-based week vs Spark's ISO week). The project never calls it: `extract(week` appears in no model. Whether BigQuery `EXTRACT(ISOWEEK ...)` matches Spark was **not probed: unverified**. The guardrail does not catch it. |
| `FORMAT_DATE('%Y/%m/%d', d)` | `2024/03/15` | `date_format(d, 'yyyy/MM/dd')` = `2024/03/15`; `'%Y/%m/%d'` raises `INCONSISTENT_BEHAVIOR_CROSS_VERSION` | `format_date_str`, `macros/polyglot/dates.sql:48-95` (translates `%Y %m %d %j %a %b %H %M %S` to `yyyy MM dd DDD EEE MMM HH mm ss`) | **A different pattern language**, not a rename: strftime vs Java DateTimeFormatter, and the argument order flips. Any other code, or a literal letter, is a compiler error on both targets (`dates.sql:55-73`). Used by `dim_date` via `format_month`. |
| Three-part identifiers `` `project.dataset.table` `` | `10` rows | **REQUIRES_SINGLE_PART_NAMESPACE**: Spark's session catalog takes two parts | the source definition's `database:` expression, `models/staging/_thelook__sources.yml` (the one file the guardrail allows to read the target) | Spark has no project level. The loader registers `thelook_ecommerce.<table>` in Spark so the same two-part name resolves; the adapter renders sources two-part (`` `thelook_ecommerce`.`orders` ``). |
| Implicit casts: `'1' + 1` | **400: `Could not cast literal "1" to type DATE`** | `2` | nothing | **Opposite directions**: BigQuery refuses, Spark coerces silently. A model written against Spark can lean on the coercion without anyone noticing, and only the BigQuery build would catch it. No model does this today: the BigQuery build passes. The guardrail has no token for it. |
| Decimal ceiling: precision > 38 | `BIGNUMERIC`: 76.76 digits, scale 38 | `cast(1 as decimal(39,2))` → **`DECIMAL_PRECISION_EXCEEDS_MAX_PRECISION: Decimal precision 39 exceeds max precision 38`** | `decimal_type(p, s)` raises on Spark above 38, `macros/polyglot/types.sql:124-142` | **A lost feature: no Spark type holds a BIGNUMERIC.** Measured through the macro: `polyglot_render --args '{include_bignumeric: true}' --target spark` → exit 1, `decimal_type(77, 38): Spark DECIMAL is capped at precision 38 (DECIMAL_PRECISION_EXCEEDS_MAX_PRECISION above it), while BigQuery reaches BIGNUMERIC at 76.76 digits of precision (scale 38), which has no Spark equivalent.` It never falls back to `double` silently; the ways out are a narrower decimal or `float_type()` (15–16 significant digits). No model needs more than 38 digits today. |
| Money: `NUMERIC` vs `DECIMAL(18,2)` | `numeric` (38,9): keeps nine decimals; `cast(1 as int64) + cast(2 as numeric)` = `3` | `decimal(18,2)`: exact to its declared scale; the same sum = `3.00000000`; `cast(1.005 as decimal(18,2))` = `1.01` | `money_type`, `macros/polyglot/types.sql:91-97` | **The measured value difference: 21 of 29 models, 54 of 54 decimal columns differ row by row.** See section 3. A bare Spark `DECIMAL` is `decimal(10,0)`, which is why money is pinned to `(18,2)`. |
| Float results derived from money | `mart_product_performance.gross_margin_rate`: 328 distinct values | the same column: **18,696** distinct values | nothing: a consequence of the row above | Not a decimal column (`float64`), so it is not in the money table, but it differs because its inputs differ: the rate is computed from cent-rounded money on Spark and nine-decimal money on BigQuery, so it scatters into many more distinct values. Any ratio, rank or bucket computed from money inherits the money difference. |
| `TIMESTAMP` and the session time zone | an absolute instant, always UTC | an instant rendered, truncated and cast to DATE **in the session time zone**; this project's session reads back `UTC` | `to_utc_timestamp`, `macros/polyglot/casting.sql:58-64`; guarded by the self-check case `session time zone is UTC` | Measured in a `Europe/Vienna` session: `cast(timestamp '2024-03-15 23:30:00+00:00' as date)` = **2024-03-16** (UTC: 03-15); `date_format(timestamp '2024-03-31 23:30:00+00:00', 'yyyy-MM')` = **2024-04** (UTC: 2024-03); a naive literal is read 1 h off. Instants are kept, but **every day and month boundary moves**: `order_date`, `dim_date`, the cohort months and the monthly marts would change silently. Every `*_at` column depends on this. |
| `DATETIME` vs `TIMESTAMP_NTZ` | `cast(datetime ... as timestamp)` = `1.7105103E9` | `cast(ts as timestamp_ntz)` = `2024-03-15 13:45:00.0` | the parity harness treats `timestamp_ntz` as its own kind | Wall-clock types exist on both but are different types from the instant types; mixing them is a type mismatch the parity gate reports. No model uses `DATETIME` or `timestamp_ntz`. |
| `ARRAY_AGG(x IGNORE NULLS)` | `2` | **unverified**: the probe ran `size(array_agg(x))`, which is not the same semantics; a proper Spark spelling (`filter (where x is not null)`) was not run | nothing | Not used by any model. |
| `ARRAY_AGG(x ORDER BY x LIMIT 2)` | `2` | **unverified**: the probe limited rows, not the aggregate | nothing | Not used by any model. |
| `FARM_FINGERPRINT('x')` | `-4503883598042011646` | `xxhash64('x')` = `-5636050478767222463` | nothing: no common native hash | **Different algorithms, different values.** Anything keyed or sampled on a native hash changes. The parity harness uses `md5` on both engines for this reason. Not used by any model. |

### 2.4 Platform and tooling (not SQL, but each one costs time)

| Construct | BigQuery | Spark | Handled by | Notes / residual risk |
|---|---|---|---|---|
| dbt adapter support | supported | dbt-oss 2.0.5 refuses it: `InvalidConfig (dbt1005): The 'spark' adapter is not yet supported by dbt` unless `DBT_ALLOW_EXPERIMENTAL_ADAPTERS=true` | the `Makefile`, `scripts/check_env.sh`, `scripts/pre_pr.sh` export it | The Spark adapter is **experimental** in this dbt release. |
| A local, in-process engine | n/a (a service) | `method: session` → `unknown variant 'session', expected one of 'thrift', 'http', 'livy', 'spark-connect'` | `scripts/start_spark.sh` runs a Spark Thrift Server on `127.0.0.1:10000` | Every Spark run, including compiling the Spark target, needs a live endpoint. |
| Profile auth | service-account key | `'user' is required when auth is 'PLAIN' or 'NONE'` | `profiles.yml` sets `user:` | |
| Fetching arrays through dbt | works | `NotImplemented: [spark] Unsupported type ARRAY_TYPE` | none needed: no model's final projection has an array | `dbt show` / `run_query` on an array column fails on Spark. |
| `CREATE OR REPLACE TABLE ... USING PARQUET` | n/a | `UNSUPPORTED_FEATURE.TABLE_OPERATION ... does not support REPLACE TABLE` on the session catalog | the loader uses `DROP TABLE IF EXISTS` + `CREATE TABLE ... USING PARQUET LOCATION` | Loader only; the models are unaffected. |
| Source data | live public dataset | a Parquet snapshot pulled by `scripts/load_spark_sources.py` (table reads, 0 bytes billed) | row counts gated against BigQuery `numRows`; 12 timestamp columns checked, no instant moved | The public dataset changes (`orders`: 124,952 rows in an older log, 124,650 on 2026-10-06). Same-data parity only holds if the snapshot is fresh: reload before comparing. |

---

## 3. The money result (value parity on the same rows)

The parity report's headline:

> **Exit 1: gating (names/types): none; rows/values: [21 models]**
>
> * models matching on every check: **8 of 29**
> * differing on names/types (gating): none
> * differing on rows/values only: 21
> * not measured: none
> * legs: Spark ok; BigQuery ok
> * digest self-check: PASS
> * same-data premise: 7 of 7 sources identical on every check

The money prediction section: **Result: CONFIRMED. 54 decimal column(s) differ row by row
(of 54 decimal columns measured; 0 match exactly).** Every difference was counted by joining
both engines on the model's primary key. Some of the evidence:

| model | column | differing rows / rows compared | max abs difference | example (Spark / BigQuery) |
|---|---|---|---|---|
| `stg_thelook__products` | `cost` | 29,035 / 29,120 | 0.005 | `20.48` / `20.484000005` |
| `fct_order_items` | `product_cost` | 180,263 / 180,778 | 0.005 | `96.48` / `96.479999721` |
| `fct_orders` | `total_cost` | 124,394 / 124,650 | 0.01884975 | `12.96` / `12.955629769` |
| `mart_daily_revenue` | `gross_margin` | 2,776 / 2,779 | 0.407096846 | `273.52` / `273.532299698` |
| `dim_distribution_centers` | `open_inventory_value` | 10 / 10 | 8.898967913 | `1083957.18` / `1083954.762238527` |
| `mart_customer_summary` | `average_order_value` | 5,443 / 100,000 | 0.01 | `39.49` / `39.48` |

Why, in one sentence: the source money columns are FLOAT64; BigQuery casts them to `NUMERIC`
and keeps nine decimals, Spark casts them to `decimal(18,2)` and keeps cents. Row by row the
difference is at most half a cent (where the Spark value is BigQuery's rounded to cents), but
sums of rounded values drift further: up to 0.41 on a day's margin and 8.90 on one
distribution centre's open inventory value. Averages of cent-rounded values can land a cent
away from the average of the unrounded ones (`average_order_value`: 0 of the differing rows are
explained by rounding alone).

**This is not a bug in either engine and the gate does not hide it.** It is the decision
`money_type()` encodes. Making the two engines agree means one side changes its rule:
round to cents on BigQuery as well, or give Spark more decimals (`decimal(38,9)` exists on
Spark: typeof read it back). Neither option was implemented or measured here, because the
client has to choose which number is the right one. Until then, the structural gate (`make pre-pr`,
`parity.py --no-same-data`) passes and the value measurement (`make value-parity`) reports
these 21 models every time.

The 8 models that match on every value: `dim_date`, `int_events__sessions`,
`int_products__returns`, `int_users__first_order_cohort`, `stg_thelook__distribution_centers`,
`stg_thelook__events`, `stg_thelook__orders`, `stg_thelook__users`. None of them has a money
column. Dates, timestamps, integers, strings, floats and surrogate keys all agree.

---

## 4. How many models ported untouched

| | count | what it means |
|---|---|---|
| Models | **29** | |
| Render for both targets | **29** | `dbt compile` exit 0 on both; the guardrail scanned 30 compiled files (29 models + 1 analysis) and found 0 foreign-dialect tokens and 0 target branches: `PORTABLE` |
| Model SQL identical to the BigQuery original | **28** | 27 byte-for-byte identical; 1 (`int_orders__item_rollup.sql`) differs only in a comment |
| …of which never touch the dialect seam | **4** | `dim_products`, `dim_users`, `fct_inventory_items`, `fct_order_items`: plain SQL over `ref()`s |
| …of which reach the seam through a macro | **24** | the model calls a macro (`int_type()`, `money_type()`, `to_utc_timestamp()`, `month_start()`, …); the macro gained a Spark branch, the model did not change |
| Genuine rewrite | **1** | `dim_date.sql`: `cross join unnest(...)` → `explode_array_rows(...)`, because Spark has no `unnest` |

Altogether, 25 model files call at least one dialect macro (the 24 above plus `dim_date`). The
most used: `int_type(` 51 calls in 19 files, `string_type(` 34 in 8, `money_type(` 25 in 14,
`to_utc_timestamp(` 12 in 5 staging models (`NOTES.md` §10). The model tree contains no
literal `qualify`, `unnest`, `safe_cast`, `element_at`, `pivot`, `string_agg` or `array_agg`:
the dialect is reached only through the macros.

The honest reading: the port was cheap because the BigQuery project **already had** a macro
seam (built earlier, when the root project gained its second engine). On a BigQuery project with dialect written inline,
each of those 25 files would have been an edit. The seam itself is 10 macro files under
`macros/polyglot/`; each gained a Spark branch.

Other files changed: comment-only edits in the yml files, `models/marts/.gitkeep` and one
test, so the tree does not name the root project's other engine; none changes rendered SQL.
All 4 tests have identical SQL. In `analyses/polyglot_showcase.sql` one `unnest` subquery was
rewritten the same way as `dim_date`.

---

## 5. The runtime: what actually ran

| | |
|---|---|
| dbt | dbt-oss **2.0.5** from the repository's `.venv`, with `DBT_ALLOW_EXPERIMENTAL_ADAPTERS=true` |
| Spark | **Spark 4.2.0** Thrift Server (HiveServer2), local, `127.0.0.1:10000`, started from the `pyspark==4.2.0` wheel on Temurin **JDK 21**, both under `~/.local/spark`. Session read back: `spark_catalog` / `default` / **`UTC`** / `4.2.0` |
| BigQuery | real BigQuery through the REST API, service-account key at `~/.config/gcp/coreychimpbot-sa.json` (outside the repo) |
| Data | the seven real `bigquery-public-data.thelook_ecommerce` tables: 10, 29,120, 100,000, 487,799, 124,650, 180,778 and 2,421,086 rows; identical on both legs (7 of 7 sources match on every check) |

| measurement | Spark | BigQuery |
|---|---|---|
| `dbt build` (this run, 2026-10-07) | exit 0: 29 models, 167 tests, 195 success, 1 warn | exit 0: the same |
| models executed by the build | **29 of 29** | **29 of 29** |
| models executed by `parity.py --same-data` | **29 of 29** (leg `ok`) | **29 of 29** (leg `ok`) |
| models not measured | 0 | 0 |
| `polyglot_selfcheck` (macro layer) | 54 ok, 1 skipped by name, 0 failed of 55 | 34 ok, 21 skipped by name, 0 failed of 55 |
| digest self-check (the parity harness's own) | PASS | PASS |

**Nothing in this catalogue is compile-only.** Every model was built by `dbt build` on both
engines and executed again, read-only, by the parity harness (each model as one compiled query
reading only the sources). The one skipped Spark self-check case is the p > 38 decimal, which
is a compiler error by design and whose failure is captured above. The 21 BigQuery skips are
by name: BigQuery has no `typeof()` and cannot cast an array to a string, so those cases are
covered through the model builds and parity instead.

**Not measured here, so not claimed:** performance. Spark ran on one local machine and
BigQuery as a service; the per-model timings in `parity-report.md` (Spark 14–140 s, BigQuery
1.4–11.5 s) compare one local machine with a warehouse service and are not a benchmark. The
**unverified** rows in section 2 are the other open items.
