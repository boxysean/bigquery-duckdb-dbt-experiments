-- T06: column pruning -- which columns does the reader ask BigQuery for?
-- Three scans of the same table; the debug "BigQuery selected fields:" line says
-- exactly what was fetched, and the wall time says whether it mattered.
LOAD bigquery;
CREATE SECRET bq_pub (TYPE bigquery, SCOPE 'bq://__DATA_PROJECT__',
                      SERVICE_ACCOUNT_PATH '__SA_PATH__');
SET bq_debug_show_queries = true;
.timer on
.print '--- (a) count(*): no columns needed'
SELECT count(*) AS n FROM bigquery_scan('__DATA_PROJECT__.usa_names.usa_1910_2013',
                                        billing_project := '__BILLING__');
.print '--- (b) one column, filtered'
SELECT sum(number) AS s FROM bigquery_scan('__DATA_PROJECT__.usa_names.usa_1910_2013',
                                           billing_project := '__BILLING__')
WHERE year = 2000;
.print '--- (c) two columns, filtered'
SELECT count(DISTINCT state) AS states, sum(number) AS s
FROM bigquery_scan('__DATA_PROJECT__.usa_names.usa_1910_2013',
                   billing_project := '__BILLING__')
WHERE year = 2000;
.print '--- (d) every column, no filter (state, gender, year, name, number)'
SELECT count(*) AS n FROM bigquery_scan('__DATA_PROJECT__.usa_names.usa_1910_2013',
                                        billing_project := '__BILLING__')
WHERE gender IS NOT NULL;
