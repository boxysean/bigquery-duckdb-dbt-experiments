-- b02: the smallest export that still exercises the whole route.
-- One mart, one wildcard, PARQUET. mart_daily_revenue is 2,761 rows / 287,144 bytes
-- of BigQuery logical storage.
EXPORT DATA OPTIONS(
  uri='gs://__BUCKET__/__PREFIX__/b02/mart_daily_revenue-*.parquet',
  format='PARQUET',
  overwrite=true) AS
SELECT * FROM `__BILLING__.experiments_dev.mart_daily_revenue`
