-- T13: does parallel reading actually happen, and does it help?
-- The extension's rule: bq_max_read_streams = 0 requests one stream per DuckDB
-- thread, but ONLY when preserve_insertion_order = false.
-- Each query transfers every column of the 5.5M-row table, so the numbers are
-- network-bound rather than aggregation-bound.
LOAD bigquery;
CREATE SECRET bq_pub (TYPE bigquery, SCOPE 'bq://__DATA_PROJECT__',
                      SERVICE_ACCOUNT_PATH '__SA_PATH__');
SELECT current_setting('threads') AS duckdb_threads;
.timer on

.print '--- (a) defaults: preserve_insertion_order=true, bq_max_read_streams=0'
SELECT current_setting('preserve_insertion_order') AS pio,
       current_setting('bq_max_read_streams') AS streams,
       count(*) AS n
FROM (SELECT * FROM bigquery_scan('__DATA_PROJECT__.usa_names.usa_1910_2013',
                                  billing_project := '__BILLING__'));

.print '--- (b) preserve_insertion_order=false, bq_max_read_streams=0 (one stream per thread)'
SET preserve_insertion_order = false;
SELECT current_setting('preserve_insertion_order') AS pio,
       current_setting('bq_max_read_streams') AS streams,
       count(*) AS n
FROM (SELECT * FROM bigquery_scan('__DATA_PROJECT__.usa_names.usa_1910_2013',
                                  billing_project := '__BILLING__'));

.print '--- (c) preserve_insertion_order=false, bq_max_read_streams=1 (forced single stream)'
SET bq_max_read_streams = 1;
SELECT current_setting('bq_max_read_streams') AS streams, count(*) AS n
FROM (SELECT * FROM bigquery_scan('__DATA_PROJECT__.usa_names.usa_1910_2013',
                                  billing_project := '__BILLING__'));

.print '--- (d) preserve_insertion_order=false, bq_max_read_streams=8 (more than the threads on this box)'
SET bq_max_read_streams = 8;
SELECT current_setting('bq_max_read_streams') AS streams, count(*) AS n
FROM (SELECT * FROM bigquery_scan('__DATA_PROJECT__.usa_names.usa_1910_2013',
                                  billing_project := '__BILLING__'));

.print '--- (e) threads=1, bq_max_read_streams=0'
SET threads = 1;
SET bq_max_read_streams = 0;
SELECT current_setting('threads') AS threads, count(*) AS n
FROM (SELECT * FROM bigquery_scan('__DATA_PROJECT__.usa_names.usa_1910_2013',
                                  billing_project := '__BILLING__'));
