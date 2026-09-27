-- b07d: control with a bogus bearer token.
CREATE SECRET tb_http_bogus (TYPE http, BEARER_TOKEN 'not-a-real-token');
SELECT count(*) FROM read_parquet('https://storage.googleapis.com/__BUCKET__/__PREFIX__/b02/mart_daily_revenue-000000000000.parquet');
