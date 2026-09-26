# bigquery-duckdb-dbt-experiments

One dbt v2 project, two targets. The same models are built against **BigQuery**
and against a local **DuckDB** file, with the dialect differences pushed into
`macros/` rather than into a forked model tree. Sean's framing: *"one single
project power both with using macros to help transpile."*

**Status: skeleton only.** This is card 1 of the series. There are no models yet
on purpose — the point of this card is that the plumbing is real and honestly
described: the DuckDB target runs end to end, the BigQuery target is configured
and says plainly that it holds no credentials, and `scripts/check_env.sh` fails
loudly when a prerequisite is missing.

## Layout

```
dbt_project.yml         dbt v2 project (no config-version; v2 does not use it)
profiles.yml            BOTH targets, committed — it holds no credentials
packages.yml            empty on purpose: every package must work on both targets
pyproject.toml + uv.lock  dbt itself, pinned (dbt-oss 2.0.5)
Makefile                make setup | check-env | duck | bq | build-both | parity | clean
models/staging/         empty (renames and casts only)
models/intermediate/    empty (joins and business logic)
models/marts/           empty — this is where parity will be measured
macros/cross_target.sql the transpile seam: adapter-dispatch macros
tests/                  empty (singular tests)
scripts/check_env.sh    prerequisite gate; fails loudly, never half-succeeds
scripts/install_prereqs.sh  dbc, the DuckDB driver, the DuckDB CLI, the community extension
scripts/run_bq.sh       the BigQuery leg: refuses clearly when credentials are absent
scripts/parity.sh       row-count comparison across both targets
```

`seeds/` is deliberately absent. Nothing in this card needs a seed, and an empty
seed directory would only imply a data contract that does not exist yet.

## The two targets

| target     | engine                | data lives in        | credentials                        | state here |
|------------|-----------------------|----------------------|------------------------------------|------------|
| `duckdb`   | DuckDB 1.5.5 via ADBC | `dev.duckdb` (local) | none                               | **runs green** |
| `bigquery` | BigQuery (GCP)        | GCP project          | Google ADC or a service-account key | **configured, never connected** |

### `duckdb`

```
type: duckdb
path: dev.duckdb        # gitignored; `make clean` deletes it
extensions: [httpfs, iceberg, bigquery]
```

Three extensions are declared, and two of them are only loadable because of a
prerequisite that is easy to miss:

* `httpfs`, `iceberg` come from the **core** extension repository and load
  directly.
* `bigquery` is a **community** extension. dbt-oss 2.0.5 cannot express that in
  `profiles.yml` — see "Known dbt v2 findings" below — so it is installed into
  DuckDB's extension cache once, by `scripts/install_prereqs.sh`, and the plain
  name then loads that cached community build.

### `bigquery`

```
type: bigquery
method: oauth                       # gcloud application-default credentials
database: coreychimpbot             # the GCP project (v2 calls it database)
schema: experiments_<DBT_ENV>       # dataset prefix per environment; DBT_ENV=dev by default
location: US
maximum_bytes_billed: 1 GB          # hard cost ceiling, override with BQ_MAXIMUM_BYTES_BILLED
```

`maximum_bytes_billed` is a real ceiling, not a convention: a query that would
bill more than the configured number of bytes **fails instead of running**. The
default is 1 GB so that no accidental query in this repository can be expensive.

This target has **never been connected**. `make bq` checks for credentials first
and exits 2 with an explanation rather than surfacing a driver authentication
error; nothing in this card requires BigQuery credentials, and nothing in it
proves the BigQuery configuration correct.

To make the leg real, pick one:

```bash
gcloud auth application-default login \
  --scopes=https://www.googleapis.com/auth/bigquery,https://www.googleapis.com/auth/cloud-platform
```

or use a service-account key file and change the output to
`method: service-account` with `keyfile: <path>` (dbt v2 supports
service-account, gcloud OAuth, and Entra workload identity federation).

## Pinned versions

| thing | pin | where it is pinned |
|---|---|---|
| dbt | `dbt-oss 2.0.5` (dbt v2, Fusion engine, Apache-2.0 build) | `pyproject.toml` + `uv.lock` |
| DuckDB engine | `1.5.5` | `dbc install duckdb` — the dbc-installed ADBC driver is DuckDB 1.5.5 |
| DuckDB CLI | `1.5.5` (`v1.5.5 (Variegata) d8cdaa33fd`) | `scripts/install_prereqs.sh`, sha256-verified |
| dbc | `0.3.0` | `scripts/install_prereqs.sh`, sha256-verified |
| community `bigquery` extension | build `27d85ad` (`installed_from = community`) | installed by `scripts/install_prereqs.sh`; the community repo publishes a single build, so there is no semver to pin |

`scripts/check_env.sh` asserts the dbt, dbc, driver, DuckDB and extension pins and
exits 1 listing every gap. The binaries can be overridden (`DBT_BIN`, `DBC_BIN`,
`DUCKDB_BIN`), which is how the failing path is demonstrated without uninstalling
anything.

## Prerequisites

```bash
make setup          # uv sync + scripts/install_prereqs.sh
make check-env      # assert everything, loudly
```

`uv sync` installs dbt v2 from `pyproject.toml`. `scripts/install_prereqs.sh`
installs what pip cannot: `dbc`, the DuckDB ADBC driver (`dbc install duckdb`),
the DuckDB CLI, and the community `bigquery` extension. It downloads from the
official release URLs, verifies a sha256, and installs into `~/.local/bin`
(`PREFIX=` overrides), so it needs no sudo.

## Running

```bash
make duck         # dbt build --target duckdb
make bq           # dbt build --target bigquery (exits 2 without credentials)
make build-both   # duck, then bq
make parity       # row counts per mart model, both targets
```

`make duck` on this skeleton, verbatim:

```
dbt-oss 2.0.5
   Loading profiles.yml
...
=================== Errors and Warnings ====================
[warning] [UnusedResourceConfigPath (dbt1097)]: Configuration paths exist in your dbt_project.yml file which do not apply to any resources.
...
[warning] [NoNodesSelected (dbt1601)]: Nothing to do. ...
==================== Execution Summary ====================
Finished 'build' with 2 warnings for target 'duckdb' [469ms]
```

Exit status 0. The two warnings are the honest consequence of shipping zero
models: the layer configurations in `dbt_project.yml` apply to no resources yet,
and there is nothing to build. Both disappear with the first model.

## What is verified

Measured on this machine on 2026-09-26, dbt-oss 2.0.5 / DuckDB 1.5.5 / dbc 0.3.0:

* `dbt build --target duckdb` → exit 0 (zero models; the warnings above).
* `dbt debug --target duckdb` → `Debugged All checks passed!` with `connection
  test: OK`, echoing the resolved connection (`path: dev.duckdb`, `schema: main`,
  `extensions: [httpfs, iceberg, bigquery]`). That is the DuckDB connection being
  opened through the dbc-installed ADBC driver with all three declared extensions.
* A real model was built once, to prove the plumbing: a throwaway
  `models/marts/tmp_parity_probe.sql` (`select 1 as x`) was `dbt build`-ed against
  DuckDB (`Succeeded model main.tmp_parity_probe (table)`), the row count was read
  back from `dev.duckdb` directly (`1`), and `make parity` compared it
  (`tmp_parity_probe  1  n/a`, exit 2 because the BigQuery leg is unavailable).
  The throwaway model was then deleted; `models/marts` is empty again. This
  exercised `scripts/parity.sh` end to end, and it is *not* evidence of parity.
* `dbt parse --target bigquery` → exit 0, i.e. `profiles.yml` renders for that
  output and the dataset resolves (`experiments_dev`). Note that parse does not
  validate profile fields at all: a junk key in the bigquery output parses without
  complaint (measured).
* `dbt debug --target bigquery` → the BigQuery adapter **resolves the profile and
  echoes it**, including `"maximum_bytes_billed": 1000000000`, then fails only the
  connection test: `AuthenticationFailed (dbt1011) ... could not find default
  credentials`. So the field is accepted by the v2 adapter; whether it is enforced
  is untested, because no query has ever run.
* `dbt run-operation to_string --args '{column_name: my_col}' --target duckdb` →
  exit 0, the dispatch macro in `macros/cross_target.sql` works.
* `scripts/check_env.sh` → exit 0 with everything installed. Exit 1 with one named
  `FAIL` line for each of: DuckDB absent (`DUCKDB_BIN=/nonexistent/duckdb`), dbc
  absent (`DBC_BIN=/nonexistent/dbc`), and the ADBC driver absent (measured by
  moving `~/.config/adbc` aside), each naming the fix.
* `scripts/install_prereqs.sh` → exercised from scratch into an empty `PREFIX`
  with `dbc` and `duckdb` removed from `PATH`: it downloaded both release assets,
  verified their sha256, installed them, and exited 0.
* The extensions really are loading: removing the DuckDB `bigquery` build from
  DuckDB's extension cache makes `dbt build`/`dbt show` fail with
  `HTTP Error: Failed to download extension "bigquery" ... (HTTP 404)`, and
  installing it back with `INSTALL bigquery FROM community` makes it pass again.

## What is NOT verified

* **The BigQuery target has never been connected.** No credentials exist here.
  `dbt debug --target bigquery` shows the adapter accepting the profile (project,
  dataset prefix, location, `maximum_bytes_billed`) and then failing on
  `could not find default credentials`, so nothing confirms that the project,
  dataset or location are the intended ones, or that `maximum_bytes_billed` is
  enforced against the real API — no query has ever run.
* **Parity is not established.** `make parity` prints `VACUOUS parity run` in this
  skeleton because `models/marts` is empty. Zero compared models is not evidence
  of parity, and the script says so instead of reporting success; with no
  BigQuery leg it exits 2.
* **No model has been transpiled.** `macros/cross_target.sql` is exercised on the
  DuckDB target only; the BigQuery branch of `string_type()` has never run.
* **No dbt tests, no seeds, no packages.** `tests/`, `seeds/` and `packages.yml`
  are empty on purpose.
* **The fallback path (a separate project for whatever cannot be transpiled) does
  not exist here.** It is card 7's job; this project is deliberately one tree.

## Known dbt v2 findings

Recorded so the next card does not have to re-derive them. All measured with
dbt-oss 2.0.5 unless stated otherwise.

1. **`extensions:` in `profiles.yml` rejects the documented name/repo pair.**
   The name/repo form documented for community extensions —

   ```yaml
   extensions:
     - name: bigquery
       repo: community
   ```

   fails with `InvalidConfig (dbt1005): Configuration Error: extensions: item 2
   must be a string, got Mapping {name, repo}`. Only plain strings are accepted.
   (The documentation for this form appears to follow the Python `dbt-duckdb`
   adapter; it is not the v2 profile schema.)
2. **`"bigquery:community"` is not an alternative.** It is concatenated into one
   extension name and 404s: `Failed to download extension "bigquerycommunity"` .
3. **A bare name is only looked up in the CORE repository.** With the community
   build absent from the cache, `bigquery` 404s against
   `extensions.duckdb.org`. Hence the out-of-band
   `INSTALL bigquery FROM community` in `scripts/install_prereqs.sh`.
4. **dbt v2's bundled DuckDB driver *can* process extensions**, so the widely
   repeated claim that it "cannot load extensions" did not reproduce here: with
   the dbc driver hidden, the bundled driver still ran the extension `INSTALL`
   statements and successfully loaded `httpfs` and `iceberg` from the core repo.
   What the bundled driver *does* change is the **engine version**: it carries
   DuckDB **1.5.4** instead of the pinned 1.5.5, silently. That version drift is
   the reason `dbc install duckdb` is a hard prerequisite in `check_env.sh`.
5. **`dbt parse` does not validate profile fields.** A junk key added to the
   bigquery output parses cleanly, so a green `dbt parse --target bigquery` says
   only that the profile renders. `dbt debug` is the command that reports on the
   fields the adapter actually read.
6. **`maximum_bytes_billed` is accepted by the v2 BigQuery adapter** and resolves
   to an integer (visible in `dbt debug --target bigquery`'s echo of the resolved
   connection). Whether the real API enforces it is untested here.
7. **`profiles.yml` does not need to live in `~/.dbt`.** `DBT_PROFILES_DIR` is
   exported by the Makefile, so the committed copy is the one in use.
