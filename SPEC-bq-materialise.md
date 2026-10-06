# SPEC — the materialised BigQuery build: make the failure legible, and price it

You are working in `/home/hermes/projects/bigquery-duckdb-dbt-experiments/.worktrees/t_fc6d405f`,
a git worktree on branch `wt/bq-materialise` of the `bigquery-duckdb-dbt-experiments` dbt v2
project, **rebased onto `origin/main` at `c02a51b`** (so `README.md`'s CI section and
`docs/gaps.md` section 10 are the post-PR-#26 text — do not touch either; your edits are
`docs/gaps.md` section 2, and the README repository-map table plus the `make bq` sentence).
Read `AGENTS.md`/`README.md`/`docs/gaps.md` first if you need orientation. Everything
you need to know that is not in the repo is in this file.

## The situation, measured today (do not re-derive it, do not contradict it)

The card that commissioned this work assumed `make bq` (the materialised BigQuery build) still
fails for a missing permission. **It does not fail any more.** Measured 2026-10-06, read-only
where it matters:

* `coreychimpbot.experiments_dev` exists (created 2026-09-27 09:23:52Z, location `US`), and this
  service account is a dataset `OWNER` on it.
* `bigquery.datasets.create` is held: a throwaway `datasets.insert` returned HTTP 200 and the
  dataset was deleted again.
* `BQ_KEYFILE=/home/hermes/.config/gcp/coreychimpbot-sa.json bash scripts/run_bq.sh` exits 0:
  `Processed: 29 models | 167 tests` / `Summary: 196 total | 195 success | 1 warn`.
* The whole build processed 1,323,806,504 bytes (1.3238 GB) and was billed 4,653,580,288 bytes
  (4.6536 GB, BigQuery's 10 MB-per-query minimum dominates 167 tiny test jobs). The **largest
  single job** processed 150,593,696 bytes (0.1506 GB). The ceiling is per job:
  `maximum_bytes_billed` = 1,000,000,000 (1 GB), so **0 of the build's jobs come near it**.
* `maximum_bytes_billed` enforcement was reproduced for the first time, with a 1000-byte ceiling:
  `HTTP 400 ... {"reason": "bytesBilledLimitExceeded", "message": "Query exceeded limit for bytes
  billed: 1000. 141557760 or higher required."}`. A job refused this way bills nothing.

What is genuinely left, and what this task builds:

1. **A preflight that names the exact missing permission** for the day the target cannot be
   written (a fresh machine, a revoked grant, or a new `DBT_ENV` whose dataset does not exist).
   Today the failure is a raw driver error; it should say what to grant.
2. **One command** that creates the dataset when it is missing and then builds.
3. **Documentation** of both, and of the price above, in the places the repo already keeps
   this kind of record.

Do not invent a failure. Do not print a "missing permission" that has not been observed.

## Deliverable 1 — `scripts/bq_preflight.py` (new file)

A read-only diagnosis of whether the materialised BigQuery path can run. It writes nothing
unless `--create` is passed, in which case it may create the target dataset and nothing else.

Requirements:

* **No new dependencies.** Python 3 stdlib only, plus the `openssl` CLI. Reuse the repo's single
  JWT implementation the way `scripts/bq_table_meta.py` already does — load
  `scripts/parity.py` with `importlib` and call its `access_token(key_path)`. Do not write a
  second token exchange.
* **Never print or copy the key's private material.** Print only `client_email`.
* **Target naming** comes from the repo's own convention (`profiles.yml`):
  project `BQ_PROJECT` (default `coreychimpbot`), dataset `experiments_<DBT_ENV>` where
  `DBT_ENV` defaults to `dev`. The key file is `BQ_KEYFILE`, falling back to
  `GOOGLE_APPLICATION_CREDENTIALS` when that is a service-account JSON.
* **Checks, in this order**, each reported in the `scripts/check_env.sh` style
  (`  ok    <what>` / `  FAIL  <what>`), with the real HTTP status and BigQuery's own message
  quoted when something fails:
  1. the access token is obtained;
  2. `datasets.get` on `<project>.<dataset>` — on 200 print the location, the creation time and
     which principal holds OWNER; on 404 the dataset is missing (see `--create` below);
  3. a trivial `jobs.query` (`SELECT 1`) proves `bigquery.jobs.create`; it processes 0 bytes and
     bills nothing. A 403 here names `bigquery.jobs.create` in BigQuery's own message;
  4. when the dataset exists, `tables.list` on it proves read access to the dataset.
* **`--create`**: when the dataset is missing, attempt `datasets.insert` (location `US`, matching
  `profiles.yml`) exactly once. On 200 say the dataset was created; on 403 quote the message and
  name `bigquery.datasets.create`. Without `--create`, do not attempt the write — say to re-run
  with `--create`, or to create the dataset in the console.
* **The unblock path is printed, not just described.** When any permission is missing, print a
  "what to grant" block with the two `gcloud` commands built at runtime from the key's
  `client_email` (never hard-code the email; it is a value from the key file):
  * `roles/bigquery.jobUser` on the project — supplies `bigquery.jobs.create`;
  * `roles/bigquery.dataEditor` on the project — supplies `bigquery.datasets.create` plus
    `bigquery.tables.create` / `bigquery.tables.updateData` / `bigquery.tables.get` /
    `bigquery.datasets.get` / `bigquery.datasets.update` inside the dataset.
  Add one line saying `gcloud` is not installed on this box and the console route is BigQuery →
  Create dataset (id `experiments_dev`, location `US`) plus IAM → grant the two roles.
* **Exit codes** (document them at the top of the file, and use them):
  * `0` — the target is ready: dataset exists, a job can be created, the dataset is readable.
  * `1` — the preflight itself could not run (no service-account key, no `openssl`, bad
    credentials, network). The caller should fall through to `dbt` unchanged.
  * `2` — a **named blocker**: the dataset is missing and could not be created, or a job cannot
    be created. The diagnosis and the "what to grant" block have been printed.
  Be explicit in the header that `2` is "named blocker" and `1` is "preflight unavailable", so
  that neither is confused with a build failure.

## Deliverable 2 — `scripts/run_bq.sh` (edit)

Keep every existing behaviour and message. Two changes:

1. **Before `exec`ing dbt**, when a service-account key file is in play (`BQ_KEYFILE`, or
   `GOOGLE_APPLICATION_CREDENTIALS`), run `python3 scripts/bq_preflight.py --create`. If it exits
   non-zero, print its output verbatim and exit with the same code — do **not** start a build
   that is going to fail with a raw driver error. If it exits 0, continue to dbt as today.
   When the credential is gcloud ADC (not a key file), skip the preflight and say so in one
   line: the preflight covers service-account keys only.
2. **`BQ_NO_PREFLIGHT=1`** skips the preflight (documented in the header). `make bq` must still
   be exactly one command that works with no environment beyond `BQ_KEYFILE`.

Update the file's header comment: the build now runs for real (2026-09-27 and again 2026-10-06);
what the wrapper promises now is that a target it cannot write says **what to grant** instead of
relaying a driver error.

## Deliverable 3 — documentation

* **`NOTES.md`** — append a new final section titled
  `# Card t_fc6d405f — the materialised BigQuery build, and what to grant when it cannot run`.
  It must contain: the measured facts in "The situation, measured today" above (dataset, build
  exit 0 with `196 total | 195 success | 1 warn`, the byte price table, the
  `bytesBilledLimitExceeded` error text verbatim); the exact commands run and their real output;
  what the new preflight does and its exit-code contract; and an honest "what this does not
  establish" list. State plainly that the card's premise (a missing permission) no longer
  reproduces, and quote the historical error text that *was* true
  (`403 Access Denied: Project coreychimpbot: User does not have bigquery.datasets.create
  permission in project coreychimpbot`).
* **`docs/gaps.md`** — update section 2 ("The BigQuery write path") surgically. The
  `maximum_bytes_billed` row must now say the ceiling **has** refused a query, with the measured
  error reason and the byte figures, and that the build is now priced. Keep the rows that are
  still open (partitioning/clustering, DDL beyond a plain build). Add the new preflight's own
  unverified path (it has not been exercised on a machine that genuinely lacks the permission) as
  an honest gap row, and add the new sources to the "Where each claim comes from" table.
* **`README.md`** — add `scripts/bq_preflight.py` to the repository-map table, and one sentence
  where `make bq` is described: it now preflights the target and names the exact permission to
  grant when the target cannot be written. Do not rewrite the README's structure.

## Deliverable 4 — `Makefile`

One line of `help` text for `bq`: mention the preflight. Do not add a new target.

## Constraints

* **Do not touch** `models/`, `macros/`, `tests/`, `profiles.yml`, `dbt_project.yml`,
  `packages.yml`, or anything under `analyses/`. This task changes the wrapper and the docs.
* **No new dependency**, no new pip/uv package, no `pip install`.
* **Nothing may write to BigQuery** except `scripts/bq_preflight.py --create` creating the one
  target dataset. `make pre-pr`, `make duck`, `make portability`, `make polyglot` and
  `make ci-compile` must not reach this code at all.
* **Never commit a key or a credential.** The service-account email and the key path
  `~/.config/gcp/coreychimpbot-sa.json` are already in this repository (`SPEC.md`,
  `NOTES.md`, `analyses/transport_b/README.md`), so quoting them in docs is fine; the key
  file's contents are not.
* **`make pre-pr` must stay green.** The parity leg needs `BQ_KEYFILE`; with
  `BQ_KEYFILE=/home/hermes/.config/gcp/coreychimpbot-sa.json` the whole script exits 0.
  Run it and paste the real output.

## How the work will be judged

I (Bruno) will, myself: read `git diff` for every changed file; run
`BQ_KEYFILE=/home/hermes/.config/gcp/coreychimpbot-sa.json bash scripts/run_bq.sh` and require
exit 0 with `Summary: 196 total | 195 success | 1 warn`; run `python3 scripts/bq_preflight.py`
and require exit 0 with the `ok` lines; run `python3 scripts/bq_preflight.py --dataset
experiments_does_not_exist` and require exit 2 with the named permission and the two `gcloud`
commands; run `BQ_KEYFILE=... bash scripts/pre_pr.sh` and require exit 0; and check that
`git status` shows no new untracked file outside the ones listed here.

Report honestly. If something cannot be done, say so in your final message rather than
weakening a check to make it pass.
