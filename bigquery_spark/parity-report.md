# Parity report - Spark vs BigQuery

Generated 2026-10-06T19:53:28+0200 by `scripts/parity.py` (same-data gating: ON (default); Spark leg: `compiled`).

## Verdict

**Exit 2: Spark or BigQuery: the self-check query failed: list index out of range**

* legs: Spark ok; BigQuery ok
* digest self-check: not run

## TRAPS, each with its decision

1. **BIGNUMERIC cannot exist on Spark.** Spark DECIMAL caps at precision 38
   (measured); `decimal_type(p > 38)` raises on Spark by design instead of
   rendering `double`. A `bignumeric` canonical type would be named here, never
   widened away.
2. **DECIMAL(18,2) vs NUMERIC.** Types compare by *kind* (decimal == numeric),
   never precision; both raw types are recorded. Values compare exactly after
   dropping trailing fractional zeros (Spark prints the declared scale, BigQuery
   the shortest form) - which is where the money prediction is decided.
3. **Floating point** compares as integer micro-units
   (`CAST(ROUND(x * 1000000) AS BIGINT/INT64)`), not as text, no tolerance.
4. **TIMESTAMP vs TIMESTAMP_NTZ**: instants compare as microseconds since the
   epoch (Spark `unix_micros`, BigQuery `UNIX_MICROS`); `timestamp_ntz`
   (BigQuery DATETIME) is its own kind, so instant-vs-wall-clock gates. The Spark
   session must be UTC (checked by the self-check).
5. **Arrays and structs** compare structurally: arrays sorted and joined with
   `|`, structs field by field, recursively. The Spark adapter cannot fetch an
   ARRAY column at all; nothing here returns one - only aggregates leave the engine.
6. **Row order and NULLS ordering**: every metric is an aggregate; the only sort
   is of an array's own values, the same on both engines.
7. **NULLs**: explicit null and distinct counts per column, so an all-NULL column
   cannot masquerade as all-zero.
8. **The live dataset**: BigQuery reads the public dataset now, Spark a snapshot;
   the sources are compared first and drift is reported as drift.

## Reproduce

```bash
make load-sources                          # the Spark snapshot of the real rows
python3 scripts/parity.py                  # --same-data is the default
python3 scripts/parity.py --self-check     # only the digest portability step
```

Both legs are read-only: each model is the ephemeral compile of the DAG, run as
one query. BigQuery needs `BQ_KEYFILE` (default
`~/.config/gcp/coreychimpbot-sa.json`) and `openssl`; queries are capped at
`BQ_MAXIMUM_BYTES_BILLED` (1 GB) each. Spark needs the Thrift Server
(`scripts/start_spark.sh`) and the loaded sources (`make load-sources`).
