-- T07: dry_run as a cost guard, compared with what BigQuery actually billed.
-- Two secrets on purpose: one scoped to the data project (reads/count(*) via the
-- Storage API), one scoped to the billing project (query jobs + job listing).
LOAD bigquery;
CREATE SECRET bq_pub (TYPE bigquery, SCOPE 'bq://__DATA_PROJECT__',
                      SERVICE_ACCOUNT_PATH '__SA_PATH__');
CREATE SECRET bq_me (TYPE bigquery, SCOPE 'bq://__BILLING__',
                     SERVICE_ACCOUNT_PATH '__SA_PATH__');
SET bq_debug_show_queries = true;
.timer on

.print '--- (a) dry run: filtered aggregate (year = 2000)'
SELECT * FROM bigquery_query('__DATA_PROJECT__',
  'SELECT /* t07 __RUN_ID__ */ state, SUM(number) AS n FROM `__DATA_PROJECT__.usa_names.usa_1910_2013` WHERE year = 2000 GROUP BY state',
  dry_run := true, billing_project := '__BILLING__');

.print '--- (b) dry run: the same aggregate with no filter'
SELECT * FROM bigquery_query('__DATA_PROJECT__',
  'SELECT /* t07 __RUN_ID__ */ state, SUM(number) AS n FROM `__DATA_PROJECT__.usa_names.usa_1910_2013` GROUP BY state',
  dry_run := true, billing_project := '__BILLING__');

.print '--- (c) the real run of (a)'
SELECT count(*) AS states_returned FROM bigquery_query('__DATA_PROJECT__',
  'SELECT /* t07 __RUN_ID__ */ state, SUM(number) AS n FROM `__DATA_PROJECT__.usa_names.usa_1910_2013` WHERE year = 2000 GROUP BY state',
  billing_project := '__BILLING__');

.print '--- (d) what BigQuery billed for the jobs this script submitted'
SELECT job_id, job_type, state, bytes_processed, total_slot_time_ms
FROM bigquery_jobs('__BILLING__')
WHERE user_email = 'coreychimpbot@coreychimpbot.iam.gserviceaccount.com'
ORDER BY creation_time DESC LIMIT 4;
