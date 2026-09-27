-- b06b: same object, with a `TYPE gcs` secret carrying placeholder HMAC keys.
INSTALL azure;
LOAD azure;
CREATE SECRET tb_gcs (TYPE gcs, KEY_ID 'placeholder-access-key', SECRET 'placeholder-secret');
SELECT count(*) FROM read_parquet('gs://__BUCKET__/__PREFIX__/b02/*.parquet');
