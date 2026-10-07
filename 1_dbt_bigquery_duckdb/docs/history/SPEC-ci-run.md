# SPEC — CI runs the DuckDB leg end to end (Kanban card t_79ea9c8b)

You are working in the git worktree of the repository `bigquery-duckdb-dbt-experiments`
(a PUBLIC repo; `.github/workflows/ci.yml` is the workflow). Python toolchain: `uv`
(dbt-oss 2.0.5 via `uv sync --frozen`).

## The task in one line

Extend `.github/workflows/ci.yml` with a job that actually RUNS the DuckDB leg — build and
tests — not just compiles it, and update the documentation for it. Nothing else changes.

## Why

CI today compiles both targets (`make ci-compile`, job `ci-compile`) and runs the portability
guardrail. `dbt compile` renders without validating: a model can compile clean, return the
wrong rows, and merge. The DuckDB leg needs no credentials and this repo is public, so Actions
minutes are free — so the DuckDB leg should be built and tested in CI. The BigQuery leg must
stay OUT of CI (no credentials in this repo's CI) and must keep reporting itself as
`n/a` / NOT ESTABLISHED rather than faked. That behaviour is correct and must not change.

## What to add: one new job in `.github/workflows/ci.yml`

Add a third job, named `ci-duckdb-run`, that runs the repository's OWN pre-PR routine —
`make pre-pr` (`scripts/pre_pr.sh`) — with the BigQuery credential deliberately blanked. Do NOT
re-implement the routine as a list of steps in YAML: one definition of the check, in the script.
Do NOT modify `scripts/pre_pr.sh`, `scripts/ci_compile_both.sh`, `scripts/check_env.sh`,
`scripts/load_duckdb_sources.sh`, `scripts/check_portability.py`, `scripts/parity.py` or the
Makefile targets. The workflow re-implements none of it.

What `make pre-pr` does (already true, do not change): check_env → the DuckDB fixture →
`scripts/check_portability.py` (the guardrail) → `scripts/parity.py`, which itself runs
`make duck` (= `dbt build --target duckdb`: the models AND the data tests) and then rebuilds a
DuckDB baseline to prove the measurements reproduce. With no credential, `parity.py` exits 2
("parity NOT established"): the DuckDB build, the tests and the guardrail all ran and passed,
and only the BigQuery value comparison is unavailable.

The job's steps must be the same pinned setup the existing jobs use (copy them verbatim, same
comments' spirit):

- `actions/checkout@v7`
- `astral-sh/setup-uv@v10.2.0` with `python-version: "3.12"` (do NOT shorten to `@v10` — that
  tag does not exist)
- `uv sync --frozen`
- `bash scripts/install_prereqs.sh` with `PREFIX: ${{ github.workspace }}/.local/bin`, then
  `echo "$PREFIX" >> "$GITHUB_PATH"` (the DuckDB CLI and dbc must be on PATH)
- the run step (below)
- a `Job summary` step with `if: always()`

`timeout-minutes: 15` (measured locally: the whole routine is ~30–51 s; the runner is slower).

### The run step: `make pre-pr`, exit code 2 is green-with-a-warning

Name the step `make pre-pr`. Blank both credential variables in its `env:` so the job holds no
credential by construction and its colour can never depend on a secret:

    BQ_KEYFILE: ""
    GOOGLE_APPLICATION_CREDENTIALS: ""

GNU make exits 2 for ANY failed recipe, so the script's own status must be recovered from make's
error line in the captured output, exactly as the existing `ci-compile` job already does for
`ci-compile] Error N`. For `make pre-pr` that line is, verified on this box (the Makefile line
number moves as the file changes, so do NOT match it):

    make: *** [Makefile:146: pre-pr] Error 2

so the regex is `grep -oE 'pre-pr\] Error [0-9]+$' … | grep -oE '[0-9]+$'`, with `|| echo 1` as
a fallback. Tee the output to `"$RUNNER_TEMP/pre-pr.log"`, and put the recovered status in
`$GITHUB_OUTPUT` as `rc`.

Map the recovered status:

- `0` — every step ok, parity established on both targets: `::notice` and exit 0.
- `2` — every other step ok (the DuckDB build, its tests and the guardrail) but the BigQuery
  value comparison was not measured: **GREEN**. Emit a `::warning` whose title names the reason,
  e.g. `::warning title=ci-duckdb-run: BigQuery value parity NOT ESTABLISHED::…`, saying the
  DuckDB leg ran end to end (build + tests + guardrail) and that the BigQuery leg is n/a
  because no `BQ_SA_KEY`/`BQ_KEYFILE` credential exists, never faked, and that
  `ci-compile-bigquery` is the job that covers the BigQuery compile. Then exit 0.
- anything else (`1` and up, including a missing error line — the fallback `1`) — a real
  finding: `::error` and exit 1. The check must go RED, never be weakened to go green.

### The Job summary step

Write to `$GITHUB_STEP_SUMMARY`, mirroring the style of the two existing summaries:

- a `## ci-duckdb-run (the DuckDB leg, end to end)` heading;
- one sentence naming what ran: `make pre-pr` = prerequisites, the fixture, the portability
  guardrail, and `scripts/parity.py` (which runs `dbt build --target duckdb` — models and tests
  — and then a DuckDB baseline rebuild that must reproduce);
- a case on the recovered `rc` (`0` / `2` / `""` = the step never ran / other) with the honest
  verdict for each, including, for `2`, that the BigQuery leg is `n/a`, NOT ESTABLISHED, that
  nothing in the run speaks to that target, and that a green run means "the DuckDB leg was
  built and tested", not "both targets were verified";
- **the runner's own dbt numbers**: if `target/run_results.json` exists, read it with `python3`
  (usable inline — a here-string is avoidable, use an inline `python3 -c` one-liner or a small
  inline script) and print a line such as
  `dbt build --target duckdb (the last build in this run): 30 models success, 168 tests pass`
  (do NOT hardcode these counts: read them from `target/run_results.json`, as the parent card
  added a model so the numbers move).
  Verified shape on this box: `results[]` entries carry `unique_id` (e.g. `model.…`,
  `test.…`) and `status` (`success` for models, `pass` for tests); `args.which == "build"`.
  Guard the whole thing: if the file is absent or unreadable, print nothing and never fail the
  step (`|| true`). Label it as the last build's own artifact;
- the `ok` / `n/a` / `FAIL` lines and the total wall time from the captured log, in a fenced
  code block, e.g.

      grep -E '^  (ok|n/a|FAIL)  |^pre-pr:' "$RUNNER_TEMP/pre-pr.log"

  (`pre_pr.sh` prints its own wall time as the last line, `pre-pr: <N.N>s`.)

### The workflow's header comment

The file opens with a long comment explaining the existing two jobs and why the BigQuery leg is
split out. Extend it (in the same voice, wrapping near 80 columns) to cover the third job:

- `ci-duckdb-run` runs `make pre-pr` — the same routine a person runs before a PR — so the
  DuckDB leg is BUILT AND TESTED on every push and PR, not merely compiled. Compiling is not
  running: `dbt compile` renders without validating, so a model can compile clean and return
  the wrong rows.
- it holds no credential by construction (both credential variables blanked), so its colour
  cannot depend on a secret; its exit 2 (the BigQuery value parity leg is `n/a`) is mapped to
  green plus a `::warning`, exactly as the gate does.
- the BigQuery *build* stays out of CI and that is deliberate: there is no credential in this
  public repository's CI, the BigQuery leg is reported unavailable rather than faked, and that
  behaviour is correct and must not change.

## Documentation

1. `docs/ci.md` — currently a table of the two jobs plus a decision table. Add `ci-duckdb-run`
   to the job table (`holds a credential?` = No, deliberately; `runs when` = always;
   `what it proves` = prerequisites install, the fixture loads, the project builds AND its tests
   pass on DuckDB, the guardrail is clean, and (when a credential is supplied) parity is
   established). Add its exit-code row to the decision table (`2` → green + `::warning`, since
   the credential is blanked by construction). Fix the sentence that says the workflow only
   compiles, and keep the "what a green compile does not mean" section accurate — a separate
   short note that a green `ci-duckdb-run` DOES mean the models and tests ran on DuckDB, while
   the BigQuery leg remains compile-only. Do not claim CI builds BigQuery.
2. `README.md`, the `## CI` section — the two bullets become three, and the paragraph that says
   "Running them would catch that (`make duck`, `make bq`); CI does not" must be corrected:
   CI now runs `make duck`-equivalent on DuckDB via `make pre-pr`, and still does not run
   `make bq` (it costs money and needs a credential). Keep the existing honest tone and the
   warning that until the `BQ_SA_KEY` secret exists CI says nothing about the BigQuery target.
3. `Makefile`: in the `help` text for `pre-pr`, add a short clause saying CI runs this too
   (job `ci-duckdb-run`). One or two lines, same style as the neighbouring entries.

Nothing else: no new secrets, no changes to the existing jobs' behaviour, no new script, no
test changes, no reformatting of untouched lines.

## Verification you must run before reporting

- `python3 -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml'))"` (the YAML
  parses; note `on:` is fine under a plain `safe_load`).
- Re-read your own diff (`git diff`) and confirm the existing two jobs are untouched except in
  the header comment.
- `git diff --stat`.

Do NOT commit. Do NOT push. Report what you changed, file by file, with the exact verification
output.
