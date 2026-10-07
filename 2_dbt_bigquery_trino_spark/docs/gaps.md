# Gaps and blind spots: what project 2 has not established

Two words are used deliberately, as in project 1:

- **Unverified**: nothing was run that could fail. It does not mean broken.
- **Blind spot**: something the current checks *cannot* see, even when they are green.

## Closed on 2026-10-07

These were open until a session with a BigQuery service-account key ran them. The evidence
is in [`value_parity.md`](value_parity.md).

| Was a gap | Result |
|---|---|
| The BigQuery build of project 2 | `make bq`: **197 pass, 1 warn, 0 error** (the deliberate dirty-data warning, as in project 1) |
| Real data on the Trino leg | `make trino-real`: the 3,347,594 real rows, downloaded from BigQuery and landed by Spark. **197 pass, 1 warn, 0 error**, the same warning with the same 137,807 rows |
| BigQuery-vs-Trino value parity | `make parity`: **30 / 30 relations identical, 887 / 887 metrics** |
| Whether decimal(38,9) money closes project 1's money gap | **Yes.** Every money sum is equal to the ninth decimal place, including both `average_order_value` metrics |
| Row-level parity (the per-column profile could miss values on the wrong rows) | `make rows`: **30 / 30 relations equal row for row**, 6,296,884 rows joined on their key, 0 of 79.8M cells different ([`row_parity.md`](row_parity.md)) |

Also measured on real data: Spark reads all 12 tables with profiles identical to Trino's.

## 1. Unverified

| Gap | Why | What closing it takes |
|---|---|---|
| **Performance and cost at scale** | One machine, single-node Trino, `local[2]` Spark. On the real 3.3M rows the Trino `dbt build` took 47 s and BigQuery's 152 s, which says nothing about a cluster or production volumes | A sized environment and production-scale data |
| **Parity in CI** | The BigQuery build, `make parity` and `make rows` need a credential, so CI (credential-free) still builds only the fixture leg. Parity was measured once, by hand | A CI secret and a scheduled job running `make bq trino-real parity rows` |
| **The cost of disabling Spark's vectorized reader** | The fix in [`challenges.md`](challenges.md) 4.1 makes Spark use its row-based Parquet reader on dbt's tables; the slowdown was not measured | A Spark read benchmark with and without the property, on real data |

## 2. Blind spots (green checks that would not notice)

| Blind spot | Why the checks miss it |
|---|---|
| **Representation, outside the measured paths** | `make rows` names the four type pairs whose text or type differs (timestamps naive vs instant, decimal padding, double scientific notation, JSON text vs JSON). A consumer that compares rendered text, or reads Trino's naive timestamps in a non-UTC session, would see differences that are not value differences. Nothing checks those consumers |
| **Spark and Trino writing the same table concurrently** | Iceberg uses optimistic concurrency, so a conflicting commit fails and retries. The round trip here is strictly sequential (Spark writes sources, then dbt, then Spark reads), so commit conflicts, retries and isolation are never exercised |
| **Table maintenance** | Every `CREATE OR REPLACE` adds a snapshot, and nothing expires snapshots, removes orphan files or compacts small files. The local stack is reset often enough to hide this; a long-lived lakehouse needs scheduled maintenance (Trino `ALTER TABLE ... EXECUTE expire_snapshots / optimize`, or Spark procedures) |
| **Catalog security and governance** | The REST fixture has no auth, and the S3 keys are static local ones. Real catalogs (Polaris, Glue, Unity, Lakekeeper) add credential vending, RBAC and multi-tenancy, which change the config and can change behaviour |
| **Spark *writing* what Trino reads, beyond the sources** | Spark produces the raw sources (BIGINT, DOUBLE, STRING, TIMESTAMP only). A Spark-produced table with decimals, nested types, `TIMESTAMP_NTZ` or schema evolution is not exercised in the Spark → Trino direction |
| **Same-type semantic drift in a cross-dialect view** | The views are unreadable by Spark today, which is safe. If someone made one readable (e.g. turned off dbt-trino quoting), Spark would re-run Trino SQL with Spark semantics, and differences that keep the type (rounding, week numbers, regex dialect) would pass every check |
| **Incremental models, snapshots, merges** | The shared model tree has none, so dbt-trino's `merge` on Iceberg and its interaction with Spark readers is untested |
| **The dbt-version split** | dbt v1 and v2 are tested separately. A model that uses a feature only one of them supports is caught by the other project's CI, but only once that model is in the shared tree |
| **Views as an interface** | Staging and intermediate views exist only in Trino. Any downstream consumer that is not Trino (Spark, a BI tool on another engine) sees only the marts |

## 3. Deliberately out of scope

- **Running dbt on Spark** (dbt-spark) as a third target: the brief is "everything goes
  to Trino". An earlier dbt v2 experiment, since removed from the repository
  ([its last version](https://github.com/boxysean/bigquery-duckdb-dbt-experiments/tree/8a8ca399eb8a54af5669df7567c888bfc85c263c/archive/dbt_v2_bigquery_spark)), did Spark-as-a-dbt-target and documents what that costs.
- **Delta Lake / Hudi**: Iceberg was chosen for its REST catalog and Trino write support
  ([`architecture.md`](architecture.md) §2).
