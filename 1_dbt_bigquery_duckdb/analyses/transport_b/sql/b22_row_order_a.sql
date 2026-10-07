-- b22: row order, export A. No ORDER BY: whatever order the storage layer hands over.
-- Source: noaa_gsod.gsod2023, 4,038,747 rows / 786 MB — big enough to be cut into more
-- than one file (the file sizes are recorded in the job listing next to this scenario).
EXPORT DATA OPTIONS(
  uri='gs://__BUCKET__/__PREFIX__/b22/a-*.parquet',
  format='PARQUET', overwrite=true) AS
SELECT stn, year, mo, da, temp
FROM `bigquery-public-data.noaa_gsod.gsod2023`
WHERE temp IS NOT NULL
