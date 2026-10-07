-- b22c: row order, export D. A third run of the identical unordered SQL, so the shard
-- evidence in b24 is three observations rather than one pair.
EXPORT DATA OPTIONS(
  uri='gs://__BUCKET__/__PREFIX__/b22/d-*.parquet',
  format='PARQUET', overwrite=true) AS
SELECT stn, year, mo, da, temp
FROM `bigquery-public-data.noaa_gsod.gsod2023`
WHERE temp IS NOT NULL
