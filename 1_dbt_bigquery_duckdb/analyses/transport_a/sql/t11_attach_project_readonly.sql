-- T11: attach a WHOLE project. Two ways to get it wrong, both real.
LOAD bigquery;
CREATE SECRET bq_pub (TYPE bigquery, SCOPE 'bq://__DATA_PROJECT__',
                      SERVICE_ACCOUNT_PATH '__SA_PATH__');
CREATE SECRET bq_me (TYPE bigquery, SCOPE 'bq://__BILLING__',
                     SERVICE_ACCOUNT_PATH '__SA_PATH__');
-- bq_debug_show_queries is deliberately OFF here: attaching a whole project makes
-- the extension send one enormous UNION ALL over every dataset's
-- INFORMATION_SCHEMA.COLUMNS, and echoing it would fill this log with megabytes of
-- generated SQL. The two failures below are the evidence.

.print '--- (a) whole project, no billing_project: the reader runs its metadata queries in the DATA project'
ATTACH 'project=__DATA_PROJECT__' AS bq_data (TYPE bigquery, READ_ONLY);
SELECT count(*) AS schemas FROM duckdb_schemas() WHERE database_name = 'bq_data';

.print '--- (b) whole project, billing_project set: metadata queries move to the paying project'
ATTACH 'project=__DATA_PROJECT__ billing_project=__BILLING__' AS bq_paid (TYPE bigquery, READ_ONLY);
SELECT count(*) AS schemas FROM duckdb_schemas() WHERE database_name = 'bq_paid';

.print '--- (c) attach the paying project itself'
ATTACH 'project=__BILLING__' AS bq_me (TYPE bigquery, READ_ONLY);
SELECT schema_name FROM duckdb_schemas() WHERE database_name = 'bq_me' ORDER BY 1;
