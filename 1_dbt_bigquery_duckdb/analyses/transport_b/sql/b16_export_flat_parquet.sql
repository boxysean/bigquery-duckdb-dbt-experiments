-- b16: the same rows as b15, as Parquet: the control for b17's comparison.
EXPORT DATA OPTIONS(
  uri='gs://__BUCKET__/__PREFIX__/b16/flat-*.parquet',
  format='PARQUET',
  overwrite=true) AS
SELECT * FROM `__BILLING__.experiments_dev.transport_b_types_flat`
