# SPEC 2 — fix the prerequisite drift the new CI job exposed (Kanban card t_79ea9c8b)

You are working in the git worktree of the PUBLIC repo `bigquery-duckdb-dbt-experiments`.
The card's first change (a new `ci-duckdb-run` job in `.github/workflows/ci.yml`) is already
committed on this branch. Its first GitHub Actions run went RED with a real finding, and this
second change fixes it.

## The failure (real CI output, run 37582016359, job `ci-duckdb-run`)

    $ python3 scripts/parity.py
        Candidate extensions: "icu", "iceberg", "parquet", "inet", "quack"
        For more info, visit https://duckdb.org/docs/stable/extensions/troubleshooting?version=v1.5.6&platform=linux_amd64&extension=bigquery
        make[1]: *** [Makefile:98: duck] Error 1
        FATAL: the DuckDB leg did not build; nothing can be compared.
      FAIL  python3 scripts/parity.py (exit 1)

The same job's `install_prereqs.sh` step printed, earlier in that run:

    [2/4] installing the DuckDB ADBC driver (this is what pins the DuckDB engine version)
    Installed duckdb 1.5.6 to /home/runner/.config/adbc/drivers
    [3/4] downloading DuckDB CLI 1.5.5
          installed .../duckdb (v1.5.5 (Variegata) d8cdaa33fd)
    [4/4] installing the community bigquery extension

## Root cause

`scripts/install_prereqs.sh` pins the DuckDB **CLI** to `DUCKDB_VERSION="1.5.5"` but installs the
ADBC driver with a bare `dbc install duckdb`, which takes dbc's **latest** — 1.5.6 today. The ADBC
driver is the DuckDB **engine dbt actually runs**, and it carries its own DuckDB version. Step 4
then installs the community `bigquery` extension using the **CLI**, so the extension lands in
DuckDB's extension cache for **1.5.5** only. When dbt's 1.5.6 engine `LOAD`s `bigquery`, that is a
cache miss; a bare extension name is only looked up in the CORE repository, where `bigquery` does
not exist, so the build fails.

This is not a CI-only problem: it is a latent break in the installer that a fresh machine hits
today. It is hidden on machines (like the one this worktree is on) where the ADBC driver was
installed earlier and is still 1.5.5. `scripts/check_env.sh` did not catch it because section 3
only asserts the driver's version **prefix** is `1.5` — so a 1.5.6 driver passes while its engine
cannot load the extension the project requires.

## What to change (only these two files)

### 1. `scripts/install_prereqs.sh` — pin the driver to the same version as the CLI

Change the driver install from the bare name to the pinned version, and say why in the comment.
Exactly:

    printf '[2/4] installing the DuckDB ADBC driver %s (this is what pins the DuckDB engine version)\n' "$DUCKDB_VERSION"
    dbc install "duckdb=$DUCKDB_VERSION"

Add a short comment above it (same voice as the file, wrapped near 80 columns) recording the
defect: a bare `dbc install duckdb` resolves to dbc's latest and silently drifts from
`DUCKDB_VERSION` (measured: 1.5.6 on 2026-10-07, while the CLI is pinned to 1.5.5); the driver's
engine is the DuckDB dbt runs, and step 4 installs the community extension for the CLI's version
only, so a drifted driver cannot load it and `make duck` fails with
`Candidate extensions: "icu", "iceberg", "parquet", "inet", "quack"` from the CORE repo.

Also extend the step-4 comment with one sentence: the extension is installed by the CLI, so the
driver must be the **same** engine version for the driver's `LOAD` to find it (see step 2).
Do not change how step 4 installs the extension.

### 2. `scripts/check_env.sh` — fail loudly on driver-version drift

Section 3 currently does:

        if [ -n "$ver" ] && [ "${ver#1.5}" = "$ver" ]; then
            fail "the installed DuckDB driver is $ver, but the project pins $DUCKDB_PIN. Fix: dbc install duckdb"
        fi

That only rejects a non-1.5 driver. Make it require the **exact** pinned version, so a drifted
driver is caught here rather than four steps later inside a dbt build.

- Add an exact-version constant next to the existing pins at the top of the file, with a comment
  tying it to `install_prereqs.sh`'s `DUCKDB_VERSION` and to the community extension, e.g.

      DUCKDB_EXACT="1.5.5"          # must equal install_prereqs.sh's DUCKDB_VERSION: the ADBC
                                    # driver is the engine dbt runs, and the community extension
                                    # is installed for this version only

- In section 3, fail when `$ver` is set and differs from `$DUCKDB_EXACT`, with a message that
  names the consequence and the fix. Keep the existing non-1.5 branch working (it can stay first,
  or be folded in) and keep the `ok` line when it passes. Suggested failure text:

      fail "the installed DuckDB ADBC driver is $ver, but install_prereqs.sh pins it to $DUCKDB_EXACT (the engine dbt runs). A different engine version cannot load the community '$COMMUNITY_EXTENSION' extension, which is installed for $DUCKDB_EXACT only. Fix: dbc install \"duckdb=$DUCKDB_EXACT\""

- Do not change sections 1, 2, 4, 5 or 6, and do not change the CLI prefix check.
- This must still pass on this machine, where the driver is 1.5.5: run it and show the output.

## Do not

- Do not touch `.github/workflows/ci.yml`, `scripts/pre_pr.sh`, `scripts/ci_compile_both.sh`,
  `scripts/parity.py`, `scripts/check_portability.py`, the Makefile, or any model.
- Do not weaken the new CI job or make anything exit 0 that should be red.
- Do not reformat untouched lines.

## Verification you must run and report

1. `bash scripts/check_env.sh` — the real output (it must pass on this machine).
2. `bash scripts/install_prereqs.sh` — the real output. It must be idempotent here (dbc already
   installed, CLI already installed, driver already 1.5.5) and must not fail. Note: it installs
   the community extension over the network and re-runs `dbc install "duckdb=1.5.5"`.
3. `git diff` of just these two files, re-read by you.
4. A one-line check that the two pins agree: `grep -n 'DUCKDB_VERSION=\|DUCKDB_EXACT=' scripts/install_prereqs.sh scripts/check_env.sh`.

Do NOT commit. Do NOT push. Report file by file with the exact verification output.