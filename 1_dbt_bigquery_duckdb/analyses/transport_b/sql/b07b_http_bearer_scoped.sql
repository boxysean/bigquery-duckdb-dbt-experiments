-- b07b: the same read with the scope added. Measured: the secret stops being applied
-- and the request goes out unauthenticated (HTTP 0 / internal error), so the working
-- form is the *unscoped* http secret above.
CREATE SECRET tb_http_scoped (TYPE http, BEARER_TOKEN '__TOKEN__', SCOPE 'storage.googleapis.com');
SELECT count(*) FROM read_parquet('https://storage.googleapis.com/__BUCKET__/__PREFIX__/b02/mart_daily_revenue-000000000000.parquet');
