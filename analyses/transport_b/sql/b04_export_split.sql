-- b04: the wildcard/split demonstration. 58,937,715 rows / 8.0 GB of BigQuery
-- logical storage. BigQuery caps one exported file at 1 GB, so this cannot come back
-- as a single object; the job's exportDataStatistics.fileCount and the object sizes in
-- the bucket are the evidence for what actually happened.
EXPORT DATA OPTIONS(
  uri='gs://__BUCKET__/__PREFIX__/b04/citibike-*.parquet',
  format='PARQUET',
  overwrite=true) AS
SELECT * FROM `bigquery-public-data.new_york_citibike.citibike_trips`
