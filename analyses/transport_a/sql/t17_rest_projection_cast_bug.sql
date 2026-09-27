-- T17: a failure mode worth knowing before it eats an afternoon.
-- On the REST path (use_rest_api := true), a DuckDB projection that mentions a
-- column twice -- typeof(col) next to col is the natural way to trip it -- makes
-- the decoder mismatch result types and the read dies with a cast error naming
-- two types that have nothing to do with each other. Same query on the default
-- Storage path is fine.
LOAD bigquery;
CREATE SECRET bq_pub (TYPE bigquery, SCOPE 'bq://__DATA_PROJECT__',
                      SERVICE_ACCOUNT_PATH '__SA_PATH__');

.print '--- (a) REST path: typeof(col) + col in the same projection'
SELECT typeof(b) AS t, b, typeof(arr) AS t2, arr
FROM bigquery_query('__DATA_PROJECT__',
  $$SELECT CAST('123456789012345678901234567890.123456789' AS BIGNUMERIC) AS b,
           ST_GEOGPOINT(1.0,2.0) AS geo, [1,2,3] AS arr, STRUCT(1 AS a, 'x' AS b) AS st,
           TIMESTAMP '2024-01-02 03:04:05 UTC' AS ts$$,
  billing_project := '__BILLING__', use_rest_api := true);

.print '--- (b) the same projection on the default Storage path'
SELECT typeof(b) AS t, b, typeof(geo) AS t_geo, typeof(arr) AS t_arr,
       typeof(st) AS t_st, typeof(ts) AS t_ts
FROM bigquery_query('__DATA_PROJECT__',
  $$SELECT CAST('123456789012345678901234567890.123456789' AS BIGNUMERIC) AS b,
           ST_GEOGPOINT(1.0,2.0) AS geo, [1,2,3] AS arr, STRUCT(1 AS a, 'x' AS b) AS st,
           TIMESTAMP '2024-01-02 03:04:05 UTC' AS ts$$,
  billing_project := '__BILLING__');
