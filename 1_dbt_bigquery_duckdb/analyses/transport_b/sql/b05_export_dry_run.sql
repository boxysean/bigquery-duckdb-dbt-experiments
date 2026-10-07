-- b05: the cost guard, before spending anything. The export shape itself, dry run:
-- EXPORT DATA reads every column of the source table, so `SELECT *` is the right
-- analogue and its predicted bytes are what the export job will bill.
-- A /* __RUN_ID__ */ comment makes the SQL text unique so BigQuery's result cache
-- cannot answer it (card 5 measured that a cached shape still reports the would-process
-- bytes, with cache_hit = true).
SELECT /* b05 __RUN_ID__ */ * FROM `bigquery-public-data.new_york_citibike.citibike_trips`
