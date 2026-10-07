-- b13c: JSON to Parquet. The documented export limitations do not mention it; the job
-- fails with the error text this scenario is here to capture.
EXPORT DATA OPTIONS(
  uri='gs://__BUCKET__/__PREFIX__/b13c/json-*.parquet',
  format='PARQUET',
  overwrite=true) AS
SELECT * FROM `__BILLING__.experiments_dev.transport_b_types_json`
