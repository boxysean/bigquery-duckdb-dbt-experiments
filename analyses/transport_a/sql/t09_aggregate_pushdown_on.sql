-- T09: the same query with bq_enable_aggregate_pushdown = true (experimental).
-- If the aggregate pushes down, the debug output shows a "query: ..." line (a
-- remote GoogleSQL query job) instead of a bare read-session row restriction.
LOAD bigquery;
CREATE SECRET bq_pub (TYPE bigquery, SCOPE 'bq://__DATA_PROJECT__',
                      SERVICE_ACCOUNT_PATH '__SA_PATH__');
SET bq_debug_show_queries = true;
SET bq_enable_aggregate_pushdown = true;
.print '--- aggregate pushdown ON: grouped sum, filtered'
SELECT state, sum(number) AS n
FROM bigquery_scan('__DATA_PROJECT__.usa_names.usa_1910_2013', billing_project := '__BILLING__')
WHERE year = 2000
GROUP BY state ORDER BY 1 LIMIT 3;
.print '--- aggregate pushdown ON: ungrouped sum over the whole table'
SELECT sum(number) AS s FROM bigquery_scan('__DATA_PROJECT__.usa_names.usa_1910_2013',
                                           billing_project := '__BILLING__');
