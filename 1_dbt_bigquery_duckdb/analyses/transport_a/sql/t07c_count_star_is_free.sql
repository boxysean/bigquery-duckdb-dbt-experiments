-- T07c: the free half of the cost guard -- a bare COUNT(*) is not a scan.
-- BigQuery answers COUNT(*) from table metadata, so the dry run reports 0 bytes while
-- touching one column (COUNT(state)) costs the whole column. Compare with t07/t07b,
-- where the aggregate really has to read columns.
LOAD bigquery;
CREATE SECRET bq_pub (TYPE bigquery, SCOPE 'bq://__DATA_PROJECT__',
                      SERVICE_ACCOUNT_PATH '__SA_PATH__');

.print '--- (a) COUNT(*) -- metadata, not a scan'
SELECT * FROM bigquery_query('__DATA_PROJECT__',
  'SELECT COUNT(*) AS n FROM `__DATA_PROJECT__.usa_names.usa_1910_2013` WHERE 424242 = 424242',
  dry_run := true, billing_project := '__BILLING__');

.print '--- (b) COUNT(state) -- one column, and it costs'
SELECT * FROM bigquery_query('__DATA_PROJECT__',
  'SELECT COUNT(state) AS n FROM `__DATA_PROJECT__.usa_names.usa_1910_2013`',
  dry_run := true, billing_project := '__BILLING__');
