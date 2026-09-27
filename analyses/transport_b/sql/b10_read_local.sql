-- b10: the same data, after the harness pulled every object down with the GCS JSON API.
-- Same question, different pipe: is a bearer-token HTTPS read good enough, or is a local
-- copy worth the extra step? The wall times are in the scenario logs.
SELECT count(*) AS rows_read FROM read_parquet('__LOCAL_DIR__/*.parquet');
SELECT sum(tripduration) AS total_tripduration,
       count(DISTINCT start_station_id) AS stations
FROM read_parquet('__LOCAL_DIR__/*.parquet');
