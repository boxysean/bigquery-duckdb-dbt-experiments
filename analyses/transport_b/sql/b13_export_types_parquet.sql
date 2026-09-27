-- b13: every type family, nested and repeated included, as Parquet.
EXPORT DATA OPTIONS(
  uri='gs://__BUCKET__/__PREFIX__/b13/types-*.parquet',
  format='PARQUET',
  overwrite=true) AS
SELECT * FROM `__BILLING__.experiments_dev.transport_b_types`
