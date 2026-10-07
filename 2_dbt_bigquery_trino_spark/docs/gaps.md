# Gaps and blind spots: what project 2 has not established

Two words are used deliberately, as in project 1:

- **Unverified**: nothing was run that could fail. It does not mean broken.
- **Blind spot**: something the current checks *cannot* see, even when they are green.

## 1. Unverified

| Gap | Why | What closing it takes |
|---|---|---|
| **The BigQuery build of project 2** | No BigQuery credential was available in the session that built this project, so `dbt build --target bigquery` has **never run** for project 2. It compiles, and the BigQuery macro branches are copied from project 1, whose BigQuery leg is built and value-measured | `BQ_KEYFILE=... make bq`. Expect it to pass: the models are byte-identical to project 1's and the BigQuery branches are unchanged |
| **BigQuery-vs-Trino value parity** | Needs the BigQuery build above, plus a harness like project 1's `scripts/parity.py` comparing the two targets on the same rows | Port `parity.py` (the Spark/Trino profile in `scripts/spark_interop.py` is a ready template) and run both legs on the real data |
| **Whether decimal(38,9) money closes project 1's money gap** | Same dependency. Project 1's row-level study predicts the cent differences disappear and leaves 7 `average_order_value` rows where division semantics differ (`DECIMAL / BIGINT`). Trino's decimal division rules are a third variant | The parity run above |
| **Real data on the Trino leg** | The Trino leg reads project 1's 41,610-row fixture, landed by Spark, not the 3.3M-row public dataset | Add Trino's BigQuery connector as a catalog and land the real tables ([`architecture.md`](architecture.md) §4) |
| **Performance and cost at scale** | One machine, small data, single-node Trino, `local[2]` Spark. The ~65 s Trino build says nothing about a cluster | A sized environment and the real data |
| **The cost of disabling Spark's vectorized reader** | The fix in [`challenges.md`](challenges.md) 4.1 makes Spark use its row-based Parquet reader on dbt's tables; the slowdown was not measured | A Spark read benchmark with and without the property, on real data |
| **CI on GitHub** | The workflow `.github/workflows/2_dbt_bigquery_trino_spark.yml` runs exactly `make pre-pr`, which passed locally from an empty stack in 287 s. It has not yet run on a GitHub runner (it triggers on pull requests and pushes to `main`) | Open a PR |

## 2. Blind spots (green checks that would not notice)

| Blind spot | Why the checks miss it |
|---|---|
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
  to Trino". The archived dbt v2 experiment
  ([`../../archive/dbt_v2_bigquery_spark/`](../../archive/dbt_v2_bigquery_spark/)) did
  Spark-as-a-dbt-target and documents what that costs.
- **Delta Lake / Hudi**: Iceberg was chosen for its REST catalog and Trino write support
  ([`architecture.md`](architecture.md) §2).
