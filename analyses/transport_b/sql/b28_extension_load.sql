-- b28: the reverse direction the extension's own way: no GCS staging by hand, no upload
-- script — `bigquery_load` writes the DuckDB table as Parquet and loads it. The
-- destination is verified in b29 against the same dump b26 wrote.
INSTALL bigquery FROM community;
LOAD bigquery;
CREATE SECRET tb_bq (TYPE bigquery, SCOPE 'bq://__BILLING__', SERVICE_ACCOUNT_PATH '__SA_PATH__');
-- reverse_src is built exactly as b26 builds it — the harness substitutes that file's
-- rendered SQL here, so this scenario does not depend on b26 having run in this process.
__REVERSE_SQL__

SELECT function_name, parameters
FROM duckdb_functions() WHERE function_name = 'bigquery_load';

SELECT success, job_id, project_id, location, destination_table, output_rows, status
FROM bigquery_load('__BILLING__', 'experiments_dev.transport_b_reverse_ext',
  source_table := 'reverse_src',
  write_disposition := 'WRITE_TRUNCATE');
