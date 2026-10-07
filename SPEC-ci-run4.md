One small change in `.github/workflows/ci.yml`, in the `ci-duckdb-run` job only.

The job's `Job summary` step builds the Markdown summary and appends it to `$GITHUB_STEP_SUMMARY`
with:

      } >> "$GITHUB_STEP_SUMMARY"

Change that single redirect so the summary is ALSO printed to the step's own stdout, using

      } | tee -a "$GITHUB_STEP_SUMMARY"

Reason: `$GITHUB_STEP_SUMMARY` is not part of the job log, so the model/test counts that step reads
from `target/run_results.json` are invisible to anyone reading the log or the API. Teeing makes the
log self-contained evidence that the build and its tests ran, without changing what the summary
page shows.

Do not change anything else in that step or in the job. Do not do it in the other two jobs.
Update nothing else in the file.

Then verify and report:
- `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); print('YAML OK')"`
- `git diff` of `.github/workflows/ci.yml`, re-read by you (it must be a one-line change).
- Re-run the extracted summary step against the current `target/run_results.json` to show the tee
  works, e.g.:
  `RUNNER_TEMP=$(mktemp -d) RC=2 GITHUB_STEP_SUMMARY=$(mktemp) bash <the extracted script>`
  or simply paste the step's `run:` block into a scratch file and run it; show that the counts
  line appears on stdout AND in the summary file.

Do NOT commit. Do NOT push.