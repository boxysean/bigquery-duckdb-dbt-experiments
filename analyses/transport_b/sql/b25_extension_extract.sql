-- b25: the extension's own forward path. `bigquery_extract` wraps an extract job and
-- returns its metadata including destination_uri_file_counts. Note what it takes: a
-- source *table*. There is no query parameter, so it cannot do what b23 does (an
-- ORDER BY) and it cannot export a join or a filter — the whole table is what you get.
INSTALL bigquery FROM community;
LOAD bigquery;
CREATE SECRET tb_bq (TYPE bigquery, SCOPE 'bq://__BILLING__', SERVICE_ACCOUNT_PATH '__SA_PATH__');

-- the signature, as the extension reports it
SELECT function_name, parameters
FROM duckdb_functions() WHERE function_name = 'bigquery_extract';

-- a mart: one file
SELECT job_id, source_table, destination_uris, format, destination_uri_file_counts, input_bytes, status
FROM bigquery_extract('__BILLING__',
  source_table := '__BILLING__.experiments_dev.mart_daily_revenue',
  destination_uris := ['gs://__BUCKET__/__PREFIX__/b25/mart-*.parquet'],
  format := 'PARQUET');

-- the same 8.0 GB table b04 exported with EXPORT DATA: same split behaviour, but this
-- one is a batch-extract job, which Google's pricing page lists as free
SELECT job_id, destination_uri_file_counts, input_bytes, status
FROM bigquery_extract('__BILLING__',
  source_table := 'bigquery-public-data.new_york_citibike.citibike_trips',
  destination_uris := ['gs://__BUCKET__/__PREFIX__/b25/citibike-*.parquet'],
  format := 'PARQUET');
