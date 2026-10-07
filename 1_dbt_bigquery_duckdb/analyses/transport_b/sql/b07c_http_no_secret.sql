-- b07c: two controls for b07, same URL, no usable credential.
--   1) no secret      -> the request never gets a credential
--   2) bogus token    -> GCS would answer 401
-- Both come back as the same DuckDB-side failure, which is what makes b07's success
-- attributable to the token rather than to the object being readable.
SELECT count(*) FROM read_parquet('https://storage.googleapis.com/__BUCKET__/__PREFIX__/b02/mart_daily_revenue-000000000000.parquet');
