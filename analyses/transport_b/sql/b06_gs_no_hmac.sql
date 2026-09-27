-- b06: reading the exported objects straight from GCS in DuckDB.
-- Two attempts, both expected to fail on this box for the same reason: DuckDB speaks
-- the GCS XML API with HMAC keys, and no HMAC key exists for the service account.
--   1) no secret at all
--   2) a TYPE gcs secret with placeholder keys
-- (b07 shows the route that does work here.)
SELECT count(*) FROM read_parquet('gs://__BUCKET__/__PREFIX__/b02/*.parquet');
