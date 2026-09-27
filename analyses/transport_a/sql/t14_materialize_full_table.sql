-- T14: the plainest possible proof that the Storage Read API read path works:
-- materialize the whole 5.5M-row table locally and check the data, not the count.
-- (The card carries a signal that read-session creation 404s on this project.)
LOAD bigquery;
CREATE SECRET bq_pub (TYPE bigquery, SCOPE 'bq://__DATA_PROJECT__',
                      SERVICE_ACCOUNT_PATH '__SA_PATH__');
.timer on
ATTACH '__TMP__/t14.duckdb' AS local (TYPE duckdb);
CREATE OR REPLACE TABLE local.t14_usa_names AS
SELECT * FROM bigquery_scan('__DATA_PROJECT__.usa_names.usa_1910_2013',
                            billing_project := '__BILLING__');
SELECT count(*) AS rows_local,
       count(DISTINCT state) AS states,
       min(year) AS min_year, max(year) AS max_year,
       sum(number) AS total_number
FROM local.t14_usa_names;
DESCRIBE local.t14_usa_names;
