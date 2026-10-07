-- b23: row order, made deterministic with ORDER BY. Same table, same wildcard, same
-- columns — the only change is the sort. This is the export shape a reproducible
-- pipeline needs, and it is the one bigquery_extract (b25) cannot express.
EXPORT DATA OPTIONS(
  uri='gs://__BUCKET__/__PREFIX__/b23/c-*.parquet',
  format='PARQUET', overwrite=true) AS
SELECT stn, year, mo, da, temp
FROM `bigquery-public-data.noaa_gsod.gsod2023`
WHERE temp IS NOT NULL
ORDER BY temp
