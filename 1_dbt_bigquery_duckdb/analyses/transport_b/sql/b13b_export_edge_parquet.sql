-- b13b: BIGNUMERIC and GEOGRAPHY on their own. Neither has an obvious Parquet type:
-- BIGNUMERIC is 76 significant digits where Parquet DECIMAL stops at 38, and GEOGRAPHY
-- is not a Parquet primitive. Isolating them means the failure (if any) is attributable.
EXPORT DATA OPTIONS(
  uri='gs://__BUCKET__/__PREFIX__/b13b/edge-*.parquet',
  format='PARQUET',
  overwrite=true) AS
SELECT * FROM `__BILLING__.experiments_dev.transport_b_types_edge`
