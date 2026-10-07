Two one-line text fixes in the same two files. Nothing else.

1. `scripts/check_env.sh`, section 3, the "driver is not installed" failure message — it currently
   ends `Fix: dbc install duckdb`. A bare install takes dbc's latest and recreates the drift this
   branch just fixed. Change it to `Fix: dbc install \"duckdb=$DUCKDB_EXACT\"`. Keep the rest of
   that sentence as it is.

2. `scripts/install_prereqs.sh`, the header comment line 6 (the numbered list of the four
   prerequisites, item 2) — it currently says `(dbc install duckdb — pins the engine version)`,
   which is no longer true. Change it to name the pinned install,
   `(dbc install "duckdb=$DUCKDB_VERSION" — pins the engine version)`.

Do not touch anything else: no code, no other messages, no reformatting.

Then run and show: `bash scripts/check_env.sh` (must still pass), and
`git diff -- scripts/check_env.sh scripts/install_prereqs.sh`. Do NOT commit. Do NOT push.