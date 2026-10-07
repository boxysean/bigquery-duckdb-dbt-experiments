-- b08: wildcards over a plain HTTPS URL. DuckDB refuses `*` on generic HTTP paths by
-- default; the flag it suggests only stops the refusal, it does not turn the URL into a
-- glob (b08b shows the request that follows and the 404 it gets).
CREATE SECRET tb_http (TYPE http, BEARER_TOKEN '__TOKEN__');
SELECT count(*) FROM read_parquet('https://storage.googleapis.com/__BUCKET__/__PREFIX__/b02/*.parquet');
