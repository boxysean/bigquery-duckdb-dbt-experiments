-- T18: second extension failure mode -- projecting out of a dry-run result.
-- bigquery_query(..., dry_run := true) is fine as SELECT *, but naming any of its
-- columns in an outer projection kills the process with a DuckDB INTERNAL error
-- (the extension indexes past the end of its own result vector). Not a permission
-- problem, not the query: the same shape as SELECT * returns 44,419,616 bytes.
LOAD bigquery;
CREATE SECRET bq_pub (TYPE bigquery, SCOPE 'bq://__DATA_PROJECT__',
                      SERVICE_ACCOUNT_PATH '__SA_PATH__');
.print '--- projecting two columns out of the dry-run table function'
SELECT total_bytes_processed AS predicted_bytes, cache_hit
FROM bigquery_query('__DATA_PROJECT__',
  'SELECT /* t18 __RUN_ID__ */ COUNT(*) AS n FROM `__DATA_PROJECT__.usa_names.usa_1910_2013` WHERE year = 2000',
  dry_run := true, billing_project := '__BILLING__');
