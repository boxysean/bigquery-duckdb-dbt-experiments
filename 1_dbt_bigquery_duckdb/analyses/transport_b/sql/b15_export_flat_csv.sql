-- b15: the CSV export that IS allowed — the flat table (no nested, no repeated).
EXPORT DATA OPTIONS(
  uri='gs://__BUCKET__/__PREFIX__/b15/flat-*.csv',
  format='CSV',
  overwrite=true,
  header=true) AS
SELECT * FROM `__BILLING__.experiments_dev.transport_b_types_flat`
