Implement the specification below exactly. Read it fully before writing anything.

Two extra rules for this run, on top of the spec:

1. **Do not run `bash scripts/run_bq.sh` or `make bq` or `make value-parity`.** They start a
   billable BigQuery build; the orchestrator runs and verifies those afterwards. Everything else
   you need is read-only or local.
2. **Do not run a billable BigQuery job of any kind.** `python3 scripts/bq_preflight.py` is
   read-only and you SHOULD run it against the real key (`BQ_KEYFILE` is exported for you) to
   check your own work. `python3 scripts/bq_preflight.py --create` is also allowed (the target
   dataset already exists, so it creates nothing). Do not run `--dataset` against anything else
   end to end.

---

