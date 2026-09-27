-- T15: type fidelity, Storage Read API path (the default for bigquery_scan /
-- bigquery_query without use_rest_api). typeof() on every column of one result.
LOAD bigquery;
CREATE SECRET bq_pub (TYPE bigquery, SCOPE 'bq://__DATA_PROJECT__',
                      SERVICE_ACCOUNT_PATH '__SA_PATH__');
.timer on

.print '--- (a) declared types, as DuckDB sees them'
SELECT typeof(bignum) AS t_bignum, typeof(num) AS t_numeric, typeof(geo) AS t_geography,
       typeof(arr_i) AS t_array_int, typeof(arr_s) AS t_array_str, typeof(st) AS t_struct,
       typeof(ts) AS t_timestamp, typeof(dt) AS t_datetime, typeof(tm) AS t_time,
       typeof(js) AS t_json, typeof(byt) AS t_bytes, typeof(iv) AS t_interval
FROM bigquery_query('__DATA_PROJECT__', $$
  SELECT CAST('123456789012345678901234567890.123456789' AS BIGNUMERIC) AS bignum,
         NUMERIC '1.23' AS num,
         ST_GEOGPOINT(-122.4, 37.7) AS geo,
         [1,2,3] AS arr_i,
         ['a','b'] AS arr_s,
         STRUCT(1 AS a, 'x' AS b) AS st,
         TIMESTAMP '2024-01-02 03:04:05 UTC' AS ts,
         DATETIME '2024-01-02 03:04:05.678901' AS dt,
         TIME '03:04:05.678901' AS tm,
         JSON '{"k":1}' AS js,
         b'\x01\x02' AS byt,
         INTERVAL 1 DAY AS iv
$$, billing_project := '__BILLING__');

.print '--- (b) values, not just types'
.mode line
SELECT bignum, num, geo, arr_i, arr_s, st, ts, dt, tm, js, byt, iv
FROM bigquery_query('__DATA_PROJECT__', $$
  SELECT CAST('123456789012345678901234567890.123456789' AS BIGNUMERIC) AS bignum,
         NUMERIC '1.23' AS num,
         ST_GEOGPOINT(-122.4, 37.7) AS geo,
         [1,2,3] AS arr_i,
         ['a','b'] AS arr_s,
         STRUCT(1 AS a, 'x' AS b) AS st,
         TIMESTAMP '2024-01-02 03:04:05 UTC' AS ts,
         DATETIME '2024-01-02 03:04:05.678901' AS dt,
         TIME '03:04:05.678901' AS tm,
         JSON '{"k":1}' AS js,
         b'\x01\x02' AS byt,
         INTERVAL 1 DAY AS iv
$$, billing_project := '__BILLING__');
.mode duckbox

.print '--- (c) a real table: TIMESTAMP columns from thelook_ecommerce.orders'
SELECT typeof(min(created_at)) AS t_created_at,
       min(created_at) AS min_created, max(created_at) AS max_created,
       count(*) AS rows_read,
       count(returned_at) AS returned_at_non_null
FROM bigquery_scan('__DATA_PROJECT__.thelook_ecommerce.orders',
                   billing_project := '__BILLING__');

.print '--- (d) a real GEOGRAPHY column, and its DuckDB type'
DESCRIBE SELECT * FROM bigquery_scan('__DATA_PROJECT__.geo_us_boundaries.counties',
                                     billing_project := '__BILLING__');
