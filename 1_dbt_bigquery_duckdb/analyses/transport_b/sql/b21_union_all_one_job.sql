-- b21: the wrong way to get two tables into one file set — UNION ALL. It is legal, it is
-- one query, and the output tells you nothing about which rows came from which table.
-- Compare with b20, where two EXPORT DATA statements produce two prefixes.
EXPORT DATA OPTIONS(
  uri='gs://__BUCKET__/__PREFIX__/b21/merged-*.parquet',
  format='PARQUET', overwrite=true) AS
SELECT 'mart_daily_revenue' AS source, CAST(revenue_date AS STRING) AS k, CAST(order_count AS STRING) AS v
FROM `__BILLING__.experiments_dev.mart_daily_revenue`
UNION ALL
SELECT 'mart_cohort_retention', CAST(cohort_month AS STRING), CAST(customers AS STRING)
FROM `__BILLING__.experiments_dev.mart_cohort_retention`
