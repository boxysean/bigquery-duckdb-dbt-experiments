-- T08: aggregates with the DEFAULT settings.
-- bq_enable_aggregate_pushdown is off by default: expect a row restriction
-- (the WHERE) to reach BigQuery, but the GROUP BY / SUM to happen in DuckDB.
LOAD bigquery;
CREATE SECRET bq_pub (TYPE bigquery, SCOPE 'bq://__DATA_PROJECT__',
                      SERVICE_ACCOUNT_PATH '__SA_PATH__');
SET bq_debug_show_queries = true;
SET bq_enable_aggregate_pushdown = false;
.print '--- aggregate pushdown OFF (default): grouped sum, filtered'
SELECT state, sum(number) AS n
FROM bigquery_scan('__DATA_PROJECT__.usa_names.usa_1910_2013', billing_project := '__BILLING__')
WHERE year = 2000
GROUP BY state ORDER BY 1 LIMIT 3;
