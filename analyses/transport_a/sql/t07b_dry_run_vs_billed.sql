-- T07b: predicted vs billed bytes for ONE query shape.
-- The /* t07b __RUN_ID__ */ comment makes the GoogleSQL text unique to this run, so
-- the real query cannot be answered from BigQuery's query-results cache and the two
-- numbers in this log are comparable. Without a fresh marker, a repeat of the same
-- query reports cache_hit = true and 0 bytes processed (that is visible in t07).
-- NOTE: the dry-run result has to be read with SELECT * -- see t18.
LOAD bigquery;
CREATE SECRET bq_pub (TYPE bigquery, SCOPE 'bq://__DATA_PROJECT__',
                      SERVICE_ACCOUNT_PATH '__SA_PATH__');
CREATE SECRET bq_me (TYPE bigquery, SCOPE 'bq://__BILLING__',
                     SERVICE_ACCOUNT_PATH '__SA_PATH__');
SET bq_debug_show_queries = true;
.timer on

.print '--- (a) dry run: bytes BigQuery says this shape will process'
SELECT * FROM bigquery_query('__DATA_PROJECT__',
  'SELECT /* t07b __RUN_ID__ */ COUNT(*) AS n FROM `__DATA_PROJECT__.usa_names.usa_1910_2013` WHERE year = 2000',
  dry_run := true, billing_project := '__BILLING__');

.print '--- (b) the real run of the same shape'
SELECT * FROM bigquery_query('__DATA_PROJECT__',
  'SELECT /* t07b __RUN_ID__ */ COUNT(*) AS n FROM `__DATA_PROJECT__.usa_names.usa_1910_2013` WHERE year = 2000',
  billing_project := '__BILLING__');

.print '--- (c) the newest query jobs in the billing project: the first row is (b)'
SELECT job_id, job_type, state, bytes_processed, creation_time
FROM bigquery_jobs('__BILLING__') WHERE job_type = 'QUERY'
ORDER BY creation_time DESC LIMIT 5;
