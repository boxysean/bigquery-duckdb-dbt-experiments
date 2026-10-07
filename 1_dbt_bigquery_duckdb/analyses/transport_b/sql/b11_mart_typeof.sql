-- b11: what the exported Parquet looks like from DuckDB's side. DESCRIBE is the type
-- mapping over the file transport; the SELECT is the values. Compare both against the
-- BigQuery schema the harness recorded for `experiments_dev.mart_daily_revenue`.
CREATE SECRET tb_http (TYPE http, BEARER_TOKEN '__TOKEN__');
DESCRIBE SELECT * FROM read_parquet('https://storage.googleapis.com/__BUCKET__/__PREFIX__/b02/mart_daily_revenue-000000000000.parquet');
SELECT * FROM read_parquet('https://storage.googleapis.com/__BUCKET__/__PREFIX__/b02/mart_daily_revenue-000000000000.parquet')
ORDER BY revenue_date LIMIT 3;
