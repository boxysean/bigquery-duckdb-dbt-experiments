-- b22b: row order, export B. Identical SQL, run again: if the order were a property of
-- the data, A and B would be byte-identical.
EXPORT DATA OPTIONS(
  uri='gs://__BUCKET__/__PREFIX__/b22/b-*.parquet',
  format='PARQUET', overwrite=true) AS
SELECT stn, year, mo, da, temp
FROM `bigquery-public-data.noaa_gsod.gsod2023`
WHERE temp IS NOT NULL
