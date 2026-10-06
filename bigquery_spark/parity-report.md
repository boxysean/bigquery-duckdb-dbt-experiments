# Parity report - Spark vs BigQuery

Generated 2026-10-06T22:09:19+0200 by `scripts/parity.py` (same-data gating: ON (default); Spark leg: `compiled`).

## Verdict

**Exit 1: digest self-check FAILED**

* legs: Spark ok; BigQuery ok
* digest self-check: **FAIL**

## Digest self-check: FAIL

Both engines render a fixture of constants (int, float, bool, date, timestamp,
string, decimal, array, struct, and an all-NULL row) through the production code
path - schema discovery, kind mapping, canonical text, md5 digest, SUM - and
every metric must be identical. The Spark session time zone must be UTC.

| metric | Spark | BigQuery |
|---|---|---|
| __rows | 6 | 6 |
| arr__distinct | 5 | 5 |
| arr__nulls | 1 | 1 |
| arr__sum | 10119176120 | 13677882513 |
| b__distinct | 2 | 2 |
| b__nulls | 1 | 1 |
| b__sum | 12525941646 | 12525941646 |
| d__distinct | 5 | 5 |
| d__nulls | 1 | 1 |
| d__sum | 8514248646 | 8514248646 |
| dec__distinct | 5 | 5 |
| dec__nulls | 1 | 1 |
| dec__sum | 13086183991 | 13086183991 |
| f__distinct | 5 | 5 |
| f__nulls | 1 | 1 |
| f__sum | 9536711546 | 9536711546 |
| i__distinct | 5 | 5 |
| i__nulls | 1 | 1 |
| i__sum | 17298272059 | 17298272059 |
| s__distinct | 5 | 5 |
| s__nulls | 1 | 1 |
| s__sum | 11063112075 | 11063112075 |
| st__distinct | 6 | 6 |
| st__nulls | 1 | 1 |
| st__sum | 12187830206 | 12187830206 |
| ts__distinct | 5 | 5 |
| ts__nulls | 1 | 1 |
| ts__sum | 10624915951 | 10624915951 |

| column | Spark kind (raw) | BigQuery kind (raw) |
|---|---|---|
| i | int64 (`bigint`) | int64 (`INTEGER`) |
| f | float64 (`double`) | float64 (`FLOAT`) |
| b | bool (`boolean`) | bool (`BOOLEAN`) |
| d | date (`date`) | date (`DATE`) |
| ts | timestamp (`timestamp`) | timestamp (`TIMESTAMP`) |
| s | string (`string`) | string (`STRING`) |
| dec | decimal (`decimal(18,2)`) | decimal (`NUMERIC`) |
| arr | array<int64> (`array<bigint>`) | array<int64> (`ARRAY<INTEGER>`) |
| st | struct<a:int64,b:string> (`struct<a:bigint,b:string>`) | struct<a:int64,b:string> (`STRUCT<a INTEGER, b STRING>`) |

Spark session time zone: `UTC`.

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
