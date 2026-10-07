# SPEC — make the CI compile check gate on what can actually pass

You are working in the repo root (`/home/hermes/projects/bigquery-duckdb-dbt-experiments/.worktrees/t_7ab06f7a`),
on branch `wt/ci-green-by-design`. Read `README.md` (section `## CI`), `docs/gaps.md` (section `## 10. CI`),
`scripts/ci_compile_both.sh`, `Makefile` (`ci-compile` target) and `.github/workflows/ci.yml` before editing.

## The defect you are fixing

`.github/workflows/ci.yml` has ONE job (`ci-compile`) that gates on the exit status of
`make ci-compile`. `scripts/ci_compile_both.sh` exits **2** when the BigQuery leg could not be
established (no `BQ_SA_KEY` repository secret). The workflow turns exit 2 into a red job. Nobody on
this machine can create the `BQ_SA_KEY` secret (the GitHub token is Actions: Read only), so `main`
carries a required check that can never go green. Observed: runs 36598771536 (failure, 7s),
36599048212 (failure, 19s), 36599339715 (failure, 21s, on `main`).

The script's honesty (exit 2 = "not established", not "broken") is CORRECT and must be kept. What
is wrong is where that state lands: it must not be a red gate.

## The change — decisions already made (implement exactly this)

### 1. Two jobs, and the gate does not depend on any secret

`ci-compile` (the check that GATES):
- keeps its job id (`ci-compile`) and therefore its check-run name;
- runs the identical command `make ci-compile`, **without** any BigQuery credential in the
  environment, so the gate can never depend on a secret existing;
- installs prerequisites in the same way it does today (`uv sync --frozen`, `bash
  scripts/install_prereqs.sh` with `PREFIX=${{ github.workspace }}/.local/bin`);
- reads the script's own status the way it does today (GNU make exits 2 for any failed recipe, so
  the script's status is recovered from make's `ci-compile] Error N` line — keep that mechanism);
- then maps the status to the job outcome:
  - `0` → `::notice`, job green;
  - `2` → **job green**, with a `::warning` annotation and a job-summary line saying the BigQuery
    compile was NOT performed in this run (keep the existing `n/a` phrasing and the
    "NOT ESTABLISHED ... this run says nothing about that target" wording), plus the job summary
    naming which job does run it. A missing credential must never be a red X, and must never be
    silent either;
  - any other non-zero → `::error` + red (a real finding);
- writes one job summary (as today, including the log excerpt block with the `ok` / `n/a` / `FAIL`
  lines quoted from the runner's own output).

`ci-compile-bigquery` (the BigQuery leg):
- second job, `needs: ci-compile`, and it must be genuinely **skipped** (GitHub shows it as skipped,
  it holds no required check) when the secret is absent;
- GitHub cannot read `secrets` in a job-level `if:`, so the gating job detects presence in a step
  (`env: BQ_SA_KEY: ${{ secrets.BQ_SA_KEY }}`, `present=true|false` written to `$GITHUB_OUTPUT`,
  exposed as a job `outputs:`), and this job's `if:` is
  `needs.ci-compile.outputs.bq_key_present == 'true'`;
- when it does run: write the key to `$RUNNER_TEMP` with `umask 077` (never echo the key), export
  `BQ_KEYFILE` and `BQ_AUTH_METHOD=service-account` through `$GITHUB_ENV`, and run the SAME command,
  `make ci-compile`, then fail the job on a non-zero status. Do not re-implement the compile, the
  credential gate or the guardrail in YAML: `make ci-compile` stays the single definition CI calls;
- because a skipped job cannot emit an annotation itself, the LOUD part of the absence is emitted by
  the gating job (`::warning` annotation + summary line). That is deliberate and must be written
  down in `docs/ci.md`.

Keep `permissions: contents: read`, the existing `on:` triggers (`push: branches: [main]`,
`pull_request:`, `workflow_dispatch:`), and the pinned action tags exactly as they are
(`actions/checkout@v7`, `astral-sh/setup-uv@v10.2.0` — do NOT shorten the setup-uv tag, `@v10` does
not exist). Update the workflow's header comment to describe the two jobs truthfully.

### 2. Do not touch the three-way contract or the scripts

`scripts/ci_compile_both.sh`, `scripts/check_env.sh`, `scripts/load_duckdb_sources.sh`,
`scripts/check_portability.py` keep their behaviour: the `0` / `1` / `2` exit contract, the
`ok` / `n/a` / `FAIL` lines naming the command, `make ci-compile` as the one definition. You may
only correct a comment in `scripts/ci_compile_both.sh` (or the `Makefile` help text) if it has become
factually wrong about CI (e.g. "this job is RED"). Do not weaken, duplicate or re-implement
anything. Do not add a flag or an env switch to the script.

### 3. Documentation

- Create `docs/ci.md`: which job gates (`ci-compile`), what the second job (`ci-compile-bigquery`)
  does and that **`skip` means the `BQ_SA_KEY` repository secret is absent, so nothing in that run
  speaks to the BigQuery target**. State the run's decision table (`0` / `1` / `2` from the script,
  and their job outcomes), the loud-not-silent rule, that the gate deliberately holds no credential,
  and that the BigQuery job becomes a real check the moment the secret is added.
- Update `README.md` `## CI` (and the repository-map row for the workflow if needed) so it matches:
  the gating job is green; the BigQuery leg is a second job that is skipped without the secret; a
  red job now means a real finding. Remove the now-false claim that the workflow's jobs are red on
  `main` until the secret is added.
- Keep the measured finding stated plainly in BOTH `README.md` and `docs/gaps.md`: a green
  `dbt compile` means "renders for both engines, no dialect leaked" — it does NOT mean the SQL is
  valid (`dbt compile` renders without validating; a deliberately broken `select ((` still reported
  `258 total | 258 success`).
- Update `docs/gaps.md` section `## 10. CI` (both the gap table row and the source row) to say the
  new truth, keeping the "unverified, not broken" framing for the BigQuery leg.

### 4. Constraints

- Write nothing outside the repo; never commit a credential, a `.env` or a key file.
- Keep the house style: comments explain WHY, measured facts are dated, no invented numbers. Do not
  claim any run result you did not observe — you cannot run GitHub Actions from here.
- Validate the YAML before you finish: `.venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`
  and `bash -n scripts/ci_compile_both.sh`, and make sure `git diff` contains only intended files.

## Deliverable

Edited `.github/workflows/ci.yml`, new `docs/ci.md`, updated `README.md` and `docs/gaps.md`
(and, only if genuinely inaccurate, a comment line in `scripts/ci_compile_both.sh` / `Makefile`).
Do not commit — leave the changes in the working tree and report what you changed and what you
verified.
