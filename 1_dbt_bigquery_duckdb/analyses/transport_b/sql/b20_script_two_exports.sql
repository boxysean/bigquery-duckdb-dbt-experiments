-- b20: the documented workaround for "one table per extract job": a script. Multiple
-- EXPORT DATA statements are allowed inside BEGIN...END, and they still cost one job each.
BEGIN
  EXPORT DATA OPTIONS(
    uri='gs://__BUCKET__/__PREFIX__/b20/revenue-*.parquet',
    format='PARQUET', overwrite=true) AS
  SELECT * FROM `__BILLING__.experiments_dev.mart_daily_revenue`;

  EXPORT DATA OPTIONS(
    uri='gs://__BUCKET__/__PREFIX__/b20/cohort-*.parquet',
    format='PARQUET', overwrite=true) AS
  SELECT * FROM `__BILLING__.experiments_dev.mart_cohort_retention`;
END;
