-- T12: READ_ONLY vs writable, part 1.
-- (a) is the local guard only: a READ_ONLY catalog must refuse DDL before any
--     remote call is attempted.
-- (b) opens a writable catalog and creates a probe table. The row insert is done
--     in a SECOND session (t12b) on purpose: see the note there.
LOAD bigquery;
CREATE SECRET bq_me (TYPE bigquery, SCOPE 'bq://__BILLING__',
                     SERVICE_ACCOUNT_PATH '__SA_PATH__');

.print '--- (a) DDL through a READ_ONLY catalog'
ATTACH 'project=__BILLING__ dataset=experiments_dev' AS bq_ro (TYPE bigquery, READ_ONLY);
CREATE TABLE bq_ro.experiments_dev.transport_a_probe (id BIGINT);

.print '--- (b) the same DDL through a writable catalog'
ATTACH 'project=__BILLING__ dataset=experiments_dev' AS bq_rw (TYPE bigquery);
DROP TABLE IF EXISTS bq_rw.experiments_dev.transport_a_probe;
CREATE TABLE bq_rw.experiments_dev.transport_a_probe (id BIGINT, note VARCHAR);
SELECT 'created (remote DDL through the attached catalog)' AS step;
