-- b14b: JSON as CSV. Not nested, not repeated — so the CSV rule does not apply to it,
-- and this is the comparison that makes b13c specific to Parquet rather than to JSON.
EXPORT DATA OPTIONS(
  uri='gs://__BUCKET__/__PREFIX__/b14b/json-*.csv',
  format='CSV',
  overwrite=true,
  header=true) AS
SELECT * FROM `__BILLING__.experiments_dev.transport_b_types_json`
