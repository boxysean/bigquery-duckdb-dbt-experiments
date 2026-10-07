# Close the fixture-versus-real schema gap

Card `t_153b4307`, branch `wt/fixture-schema-gap`. Work in the repo root (this worktree).

## The gap, measured

`bigquery-public-data.thelook_ecommerce` carries two columns the local fixture does not:
`users.user_geom` and `distribution_centers.distribution_center_geom`, both **GEOGRAPHY** on
BigQuery (`scripts/bq_table_meta.py`-style `tables.get` metadata, 2026-10-07). The fixture
(`scripts/fixtures/thelook_ecommerce.sql`) loads them as nothing at all, so its schema is a
**subset**. Provenance: `analyses/value_parity/logs/loader.log:103-106` (the real loader's own
"Real vs fixture schema" diff prints `only in real GEOMETRY` twice), `docs/gaps.md` section 1.

Nothing reads them today (every staging model renames an explicit column list), so the
difference is silent: `make portability` (the guardrail) passes, `make pre-pr` passes, and a
model that started reading `user_geom` would reference a column the fixture does not define.

DuckDB 1.5.5 (this project's pin) has a **native `GEOMETRY` type** and casts WKT text to it with
no extension (`select 'POINT(1 2)'::GEOMETRY` works; `select typeof(...)` -> `GEOMETRY`).
BigQuery spells the same idea `GEOGRAPHY`. So a portable geometry type **is** possible — this is
not the "impossible" branch of the card.

## What to build

### 1. The fixture gains the two columns (closes the gap)

`scripts/fixtures/thelook_ecommerce.sql`:

* `distribution_centers` — wrap the `VALUES` list in a CTE so the point can be built from the
  already-named columns, and append the column **last** (the real table has it last):

```sql
CREATE OR REPLACE TABLE thelook_ecommerce.distribution_centers AS
WITH centers AS (
    SELECT * FROM (VALUES
        (1,  'Memphis TN',                                 35.1174, -89.9711),
        ... unchanged rows ...
        (10, 'Savannah GA',                                32.0167, -81.1167)
    ) AS t(id, name, latitude, longitude)
)
SELECT
    id::BIGINT                                                                     AS id,
    name::VARCHAR                                                                  AS name,
    latitude::DOUBLE                                                               AS latitude,
    longitude::DOUBLE                                                              AS longitude,
    ('POINT(' || longitude::VARCHAR || ' ' || latitude::VARCHAR || ')')::GEOMETRY   AS distribution_center_geom
FROM centers;
```

* `users` — wrap the existing final `SELECT ... FROM named ORDER BY id` in one more CTE
  (`located`), then append the column from the `latitude`/`longitude` it already computed, so
  the point and the stored lat/lon are the same numbers:

```sql
located AS (
    SELECT
        ... the existing final select list, unchanged, WITHOUT the trailing "ORDER BY id" ...
    FROM named
)
SELECT
    *,
    ('POINT(' || longitude::VARCHAR || ' ' || latitude::VARCHAR || ')')::GEOMETRY AS user_geom
FROM located
ORDER BY id;
```

Notes:
* Every other table, row count, value and column is unchanged. The old final select's columns
  must come out in the same order as before, with `user_geom` appended.
* Checked: no model reads these tables with `select *` in its *final* select (each staging model
  renames an explicit list), so appending a source column changes no model's output.
* Update the file's header comment: the fixture now mirrors the real schema **including** the two
  geometry columns, and say the type mapping (BigQuery `GEOGRAPHY` -> DuckDB `GEOMETRY`) and that
  the fixture cannot call the seam macro because it is plain SQL run by the `duckdb` CLI.

### 2. The mapping gets a home in the seam

`macros/polyglot/types.sql` — append a `geography_type()` macro in the file's existing style
(`geography_type()` -> `adapter.dispatch(...)`; `default__geography_type()` -> `geometry`;
`bigquery__geography_type()` -> `geography`), with a doc comment saying BigQuery's `GEOGRAPHY` is
spherical/WGS84 while DuckDB's native type is spelled `GEOMETRY`, and that the two real columns
are `GEOGRAPHY`. It is the type a model would cast through; the fixture uses the DuckDB spelling
directly. No model is changed to use it.

### 3. The declared contract says so

`models/staging/_thelook__sources.yml`:
* append `user_geom` to `users` and `distribution_center_geom` to `distribution_centers`, last in
  each list, described as `GEOGRAPHY` (the real BigQuery type), WGS84 lon/lat;
* extend the header comment's "On DuckDB they arrive as ..." list with `GEOMETRY`.

### 4. The check that keeps it closed — `scripts/check_source_schema.py` (new)

Stdlib only, runnable from the repo root, same idiom and exit codes as
`scripts/check_portability.py` (`0` ok, `1` findings, `2` could not run). It proves the **fixture
schema IS the real schema and IS the declared schema**, so a model can no longer reference a real
column the fixture lacks:

* **build the fixture itself** into a scratch `dev.duckdb` under `target/schema_check/` (the same
  way `scripts/load_duckdb_sources.sh` does; the catalog is therefore named `dev`, which is what
  compiled SQL references) — do not read the developer's `dev.duckdb`, and do not require it;
* **arm A — fixture vs declared**: for each of the 7 tables, the fixture's column names
  (`information_schema.columns`, in order) against the columns declared in the source yml,
  read from `target/manifest.json` after `dbt parse --target duckdb` (offline, no credentials);
* **arm B — declared vs real**: the same declared names against the committed real-schema record
  (below). Catches contract drift;
* **arm C — fixture vs real**: every fixture column **and its DuckDB type** against the record,
  through one explicit mapping table:
  `INTEGER/INT64 -> BIGINT`, `FLOAT/FLOAT64 -> DOUBLE`, `STRING -> VARCHAR`,
  `TIMESTAMP -> TIMESTAMP WITH TIME ZONE`, `GEOGRAPHY/GEOMETRY -> GEOMETRY`;
* **arm D — a model that reads a source must bind against the fixture**: `dbt compile --target
  duckdb` into `target/schema_check/compiled/`, take every compiled model whose SQL references one
  of the 7 `thelook_ecommerce` source relations, and run DuckDB `EXPLAIN` on it against the
  scratch fixture database (DuckDB's own binder, so it is the same binding `dbt build` does, and
  it costs no rows). A `Binder Error ... Referenced column "x" not found` is a finding naming the
  model. A model that could not be bound for another reason (it reads a model as well as a
  source) is printed in its own list with the error, and counted in the summary — never silently
  skipped.
* findings print one line each with the table/column/model and which side it is missing from;
  the summary prints the counts per arm and a final `FIXTURE SCHEMA OK` / `FIXTURE SCHEMA: N
  finding(s)`.

Modes:
* default — run the arms;
* `--emit` — refresh `scripts/fixtures/real_schema.json` (below) from BigQuery and exit; needs
  `BQ_KEYFILE`; read-only `tables.get` metadata, no query job, costs nothing;
* `--demo` — the repo's existing idiom for proving a guardrail can fail (see
  `scripts/check_portability.py:306-353`): write a temporary model
  `models/staging/_schema_demo.sql` that selects a column the fixture does not define from
  `{{ source('thelook_ecommerce', 'users') }}`, run the check, require it to fail with a finding
  naming that column and that model, delete the file, run the check again and require it to pass.
  Exit non-zero if either half does not behave. Use `try/finally` so an interrupt still deletes
  the file.

`scripts/fixtures/real_schema.json` (new, committed): the real tables' schema, captured from the
BigQuery REST `tables.get` metadata (`schema.fields`), with provenance in the file —
`bigquery-public-data.thelook_ecommerce`, the endpoint, the capture time in UTC, and per table the
column list (`name`, `type`, `mode`, in order). Emit it with `--emit` rather than hand-writing it.

### 5. Wire it in

* `Makefile`: a `check-schema` target that runs the script, added to `.PHONY` and to `make help`
  next to `portability`.
* `scripts/pre_pr.sh`: a new step, after the portability guardrail and before parity, with the
  header's numbered list updated. It exits 0/1 like the guardrail, so the existing `step` helper
  handles it unchanged.
* `README.md`: mention `make check-schema` in the paragraph that already lists `make portability`
  and `make ci-compile` (one clause; do not rewrite the section).
* `docs/gaps.md`:
  * section 1, the row **"The fixture's schema is a subset of the real one"** -> mark it
    **Closed** with what closed it (the fixture now carries both columns as DuckDB `GEOMETRY`;
    `scripts/check_source_schema.py` proves fixture == declared == real on every run, `make
    check-schema`, part of `make pre-pr`), keeping the historical measurement and its source;
  * section 3, the two macro counts ("10 of 26 dialect macros ...", "10 are not called directly by
    any model") -> the measured numbers after adding `geography_type` (re-run the counting method
    in `docs/move_to_duckdb.md:98-116` / `docs/challenges.md` "The verdict"; do not guess — the
    new macro has a BigQuery branch and no model calls it);
  * the final "Where each claim comes from" table: add rows for the new evidence (the record file,
    the check, the demo).

Do **not** write the `NOTES.md` card section — the orchestrator does that with the real
verification output.

## Constraints

* No model semantics change: no model's SQL is edited, no column is added to or removed from a
  model's output, no test changes.
* No secret, key path or credential in the repo. `real_schema.json` holds only public schema
  metadata.
* Keep the fixture small: the two columns come from lat/lon that is already there.
* Do not `git commit`; leave the work in the working tree for review.

## Verify in this order (run them, read them)

```
make fixtures                       # fixture still loads, coherent, 7 tables
make check-schema                   # arms A-D pass on the fixed fixture
python3 scripts/check_source_schema.py --demo   # fails as designed, then passes
python3 scripts/check_source_schema.py --emit   # only if BQ_KEYFILE is set (read-only metadata)
make portability                    # 0 findings, both renders
make duck                           # the DuckDB leg builds and its tests pass
```

Report, as the final answer: the exact commands run, their real exit codes, and the numbers
(models/tests, findings, tokens) each printed. Do not summarise a command you did not run.
