-- b19: "You cannot export data from multiple tables in a single extract job."
-- What that does and does not mean, measured: two EXPORT DATA statements in a single
-- request are accepted as an implicit script and run as two child jobs (one extract job
-- each, each with its own 10 MiB billing floor). What no single statement can do is
-- produce two tables' worth of separated output — see b21 for that.
EXPORT DATA OPTIONS(
  uri='gs://__BUCKET__/__PREFIX__/b19/a-*.parquet',
  format='PARQUET', overwrite=true) AS
SELECT * FROM `__BILLING__.experiments_dev.mart_daily_revenue`;

EXPORT DATA OPTIONS(
  uri='gs://__BUCKET__/__PREFIX__/b19/b-*.parquet',
  format='PARQUET', overwrite=true) AS
SELECT * FROM `__BILLING__.experiments_dev.mart_cohort_retention`
