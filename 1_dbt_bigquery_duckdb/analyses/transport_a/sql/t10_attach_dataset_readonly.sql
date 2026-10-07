-- T10: attach ONE dataset (the form that works for public data: the data project
-- is named in `project`, the paying project in `billing_project`).
LOAD bigquery;
CREATE SECRET bq_pub (TYPE bigquery, SCOPE 'bq://__DATA_PROJECT__',
                      SERVICE_ACCOUNT_PATH '__SA_PATH__');
ATTACH 'project=__DATA_PROJECT__ dataset=usa_names billing_project=__BILLING__'
    AS bqnames (TYPE bigquery, READ_ONLY);
SELECT table_name FROM duckdb_tables() WHERE database_name = 'bqnames' ORDER BY 1;
SELECT count(*) AS n FROM bqnames.main.usa_1910_2013;
SELECT min(year) AS min_year, max(year) AS max_year FROM bqnames.main.usa_1910_2013;
