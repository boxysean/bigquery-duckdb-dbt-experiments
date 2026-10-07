-- b09: read a whole multi-file export in DuckDB, over HTTPS, with the object list the
-- harness read back from the bucket. __URLS__ is substituted with a DuckDB list literal.
-- The count is checked against the source table's row count and against
-- exportDataStatistics.rowCount from the export job (b04).
CREATE SECRET tb_http (TYPE http, BEARER_TOKEN '__TOKEN__');
SELECT count(*) AS rows_read FROM read_parquet(__URLS__);
SELECT count(*) AS files,
       min(c) AS min_rows_per_file,
       max(c) AS max_rows_per_file
FROM (SELECT filename, count(*) AS c FROM read_parquet(__URLS__, filename=true) GROUP BY filename);
