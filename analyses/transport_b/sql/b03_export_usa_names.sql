-- b03: the head-to-head table. Transport A (card 5) materialised this exact table
-- through the Storage Read API in 11.7 s (11.2 s and 22.2 s in other runs) and 120 MiB
-- of peak RSS. Transport B's total is this export job plus the read-back.
EXPORT DATA OPTIONS(
  uri='gs://__BUCKET__/__PREFIX__/b03/usa_names-*.parquet',
  format='PARQUET',
  overwrite=true) AS
SELECT * FROM `bigquery-public-data.usa_names.usa_1910_2013`
