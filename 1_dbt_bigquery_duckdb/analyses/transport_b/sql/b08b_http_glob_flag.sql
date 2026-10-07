-- b08b: the flag DuckDB suggests.
CREATE SECRET tb_http (TYPE http, BEARER_TOKEN '__TOKEN__');
SET allow_asterisks_in_http_paths = true;
SELECT count(*) FROM read_parquet('https://storage.googleapis.com/__BUCKET__/__PREFIX__/b02/*.parquet');
