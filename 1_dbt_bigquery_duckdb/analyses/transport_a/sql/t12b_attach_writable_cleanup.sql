-- T12b: READ_ONLY vs writable, part 2, and the cleanup.
-- A separate DuckDB session inserts into the table t12 created, reads it back
-- through the attached catalog, verifies the row remotely with a query job, then
-- drops the table. t12c then re-lists the dataset remotely.
--
-- Why a second session: inserting into a table created moments earlier IN THE SAME
-- session fails on the first attempt with a Storage Write API NOT_FOUND ("Requested
-- entity was not found") -- see analyses/transport_a/README.md. Inserting into a
-- pre-existing table works, but the extension retries first (the "Retrying..." lines
-- are the Storage Write API, and the insert is slow: see the timings in the log).
LOAD bigquery;
CREATE SECRET bq_me (TYPE bigquery, SCOPE 'bq://__BILLING__',
                     SERVICE_ACCOUNT_PATH '__SA_PATH__');
.timer on
ATTACH 'project=__BILLING__ dataset=experiments_dev' AS bq_rw (TYPE bigquery);
INSERT INTO bq_rw.experiments_dev.transport_a_probe VALUES (1, 'transport a probe');
SELECT id, note FROM bq_rw.experiments_dev.transport_a_probe;
SELECT n AS rows_seen_by_a_query_job FROM bigquery_query('__BILLING__',
  'SELECT COUNT(*) AS n FROM `__BILLING__.experiments_dev.transport_a_probe`');
DROP TABLE bq_rw.experiments_dev.transport_a_probe;
