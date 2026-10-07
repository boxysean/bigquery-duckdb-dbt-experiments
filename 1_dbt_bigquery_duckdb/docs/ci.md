# CI: which job gates, and what each colour means

The workflow is [`.github/workflows/ci.yml`](../.github/workflows/ci.yml). It runs on every
push to `main`, every pull request, and on demand (`workflow_dispatch`). Two of its jobs
compile: they run the same command, `make ci-compile`
([`scripts/ci_compile_both.sh`](../scripts/ci_compile_both.sh)). The third, `ci-duckdb-run`,
builds and tests the DuckDB leg end to end by running `make pre-pr`
([`scripts/pre_pr.sh`](../scripts/pre_pr.sh)). Both are the commands to run locally before a
PR. The workflow re-implements none of them: not the compile, not the build, not the
credential gate, not the guardrail.

## The three jobs

| job | holds a credential? | runs when | what it proves |
|---|---|---|---|
| **`ci-compile`** (the gate) | **No, deliberately.** `BQ_KEYFILE` and `GOOGLE_APPLICATION_CREDENTIALS` are blanked on its `make ci-compile` step. | always | the prerequisites install, the DuckDB fixture loads, the project compiles for DuckDB, and the portability guardrail is clean |
| **`ci-compile-bigquery`** (the BigQuery leg) | Yes: the `BQ_SA_KEY` repository secret, written to `$RUNNER_TEMP` with `umask 077` and handed over as `BQ_KEYFILE` + `BQ_AUTH_METHOD=service-account`. | only when the `BQ_SA_KEY` secret exists (`needs: ci-compile`) | all of the above, plus that the project compiles for BigQuery with a service-account-shaped key |
| **`ci-duckdb-run`** (the DuckDB leg, end to end) | **No, deliberately.** `BQ_KEYFILE` and `GOOGLE_APPLICATION_CREDENTIALS` are blanked on its `make pre-pr` step. | always | the prerequisites install, the fixture loads, the project builds **and its tests pass** on DuckDB (`dbt build --target duckdb`, then a DuckDB baseline rebuild that must reproduce), the portability guardrail is clean, and (when a credential is supplied) parity is established |

`ci-compile` is the check that gates. It holds no credential so that its colour can never
depend on a secret existing: the token used to build this repository cannot create repository
secrets (Actions: Read only), and a required check that is red until someone with more access
acts is a check nobody here can make green. Runs 36598771536, 36599048212 and 36599339715 (the
last on `main`) were red for exactly that reason under the previous one-job workflow.

**`ci-compile-bigquery` shown as skipped means the `BQ_SA_KEY` repository secret is absent, so
nothing in that run speaks to the BigQuery target.** GitHub cannot read `secrets` in a job-level
`if:`, so the gate detects the secret in a step (`present=true|false` to `$GITHUB_OUTPUT`,
exposed as the job output `bq_key_present`) and the BigQuery job's `if:` is
`needs.ci-compile.outputs.bq_key_present == 'true'`. The job is also skipped when the gate
itself is red (`needs` requires the gate to succeed); in that case the red gate is the finding.

The moment the secret is added, `ci-compile-bigquery` runs on every push and PR and is a real
check: any non-zero status from `make ci-compile` fails it. Whether to make it a *required*
check is then a branch-protection decision.

## Decision table

The script's exit contract is unchanged (`0` / `1` / `2`, see its header). What each job does
with it:

| script exit | meaning | `ci-compile` (no credential) | `ci-compile-bigquery` (with the key) |
|---|---|---|---|
| `0` | every step ok, both targets compiled | green, `::notice` (does not occur here: the credential is blanked) | green, `::notice` |
| `1` | a real finding: a prerequisite, the fixture, a compile, the key's shape or the guardrail | **red**, `::error` | **red**, `::error` |
| `2` | every other step ok, BigQuery compile `n/a`: not established | **green**, `::warning` + a job-summary line (secret absent), or `::notice` naming `ci-compile-bigquery` (secret present) | **red**, `::error` (a key was supplied, so `n/a` is not expected) |

GNU make exits 2 for any failed recipe, so both jobs recover the script's own status from
make's `ci-compile] Error N` line.

`ci-duckdb-run` applies the same mapping to `scripts/pre_pr.sh`'s exit (`0` / `1` / `2`, see
its header), recovered from make's `pre-pr] Error N` line:

| script exit | meaning | `ci-duckdb-run` (no credential) |
|---|---|---|
| `0` | every step ok, parity established on both targets | green, `::notice` (does not occur here: the credential is blanked) |
| `1` | a real finding: a prerequisite, the fixture, the DuckDB build or a test, the guardrail, or a baseline that did not reproduce | **red**, `::error` |
| `2` | every other step ok (the DuckDB build, its tests and the guardrail), BigQuery value parity `n/a`: not established | **green**, `::warning` titled `BigQuery value parity NOT ESTABLISHED` + a job-summary line (always, since the credential is blanked by construction) |

## Loud, not silent

A missing credential is not a finding, so it must not be a red X. It must not be a quiet green
either. A skipped job cannot emit an annotation, so the loud part is emitted by the gate: when
the secret is absent, `ci-compile` raises a `::warning` titled `BigQuery NOT ESTABLISHED` and its
job summary says the BigQuery leg is `n/a`, NOT ESTABLISHED, that the run says nothing about
that target, and that `ci-compile-bigquery` (the job that runs it) was skipped. Both job
summaries quote the runner's own `ok` / `n/a` / `FAIL` lines and `Processed:` / `Summary:`
counts.

In the gate, the script's `n/a` line and its `NOT ESTABLISHED` banner are printed on every
run, including runs where the secret exists: the gate withholds the credential by
construction, and the banner's "(no BQ_SA_KEY secret)" refers to that job's environment.

## What a green compile does not mean

A green `dbt compile` means the project **renders** for the engine(s) compiled and no
target-specific dialect leaked. It does **not** mean the SQL is valid: `dbt compile` renders
without validating. Measured on 2026-09-29 with a temporary broken model, `select (( from ...`
still reported `258 total | 258 success` and was written to `target/compiled/` verbatim. Even
with the key, the BigQuery compile issues no query and does not authenticate, so it is not a
live connection or a build either; that is `make bq` / `make value-parity`, which cost money
and do not run in CI. See [`README.md`](../README.md#ci) and [`gaps.md`](gaps.md) §10.

## What a green `ci-duckdb-run` does mean

A green `ci-duckdb-run` **does** mean the models were built and the data tests ran and passed
on DuckDB, so invalid SQL or a failing test on that target turns it red. Its job summary
quotes the runner's own model and test counts from `target/run_results.json` and the routine's
`ok` / `n/a` / `FAIL` lines. It says nothing about the BigQuery target: no credential exists in
this repository's CI, so the BigQuery value comparison is reported `n/a` rather than faked, and
on BigQuery CI remains compile-only (`ci-compile-bigquery`, when the secret exists).
