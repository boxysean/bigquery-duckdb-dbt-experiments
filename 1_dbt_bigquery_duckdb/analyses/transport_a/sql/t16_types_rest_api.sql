-- T16: the same types through the REST API query path, use_rest_api := true.
-- Kept in small, single-purpose queries: the REST decoder is not as forgiving as
-- the Storage reader (see t17 for the shape that fails).
LOAD bigquery;
CREATE SECRET bq_pub (TYPE bigquery, SCOPE 'bq://__DATA_PROJECT__',
                      SERVICE_ACCOUNT_PATH '__SA_PATH__');

SELECT typeof(geo) AS t_geo, geo FROM bigquery_query('__DATA_PROJECT__',
  $$SELECT ST_GEOGPOINT(-122.4, 37.7) AS geo$$,
  billing_project := '__BILLING__', use_rest_api := true);

SELECT typeof(arr_i) AS t_array, arr_i, typeof(st) AS t_struct, st
FROM bigquery_query('__DATA_PROJECT__',
  $$SELECT [1,2,3] AS arr_i, STRUCT(1 AS a, 'x' AS b) AS st$$,
  billing_project := '__BILLING__', use_rest_api := true);

SELECT typeof(bignum) AS t_bignum, bignum, typeof(num) AS t_numeric, num
FROM bigquery_query('__DATA_PROJECT__',
  $$SELECT CAST('123456789012345678901234567890.123456789' AS BIGNUMERIC) AS bignum,
           NUMERIC '1.23' AS num$$,
  billing_project := '__BILLING__', use_rest_api := true);

.print '--- bq_bignumeric_as_varchar = false (default is true): a small BIGNUMERIC stays VARCHAR'
SET bq_bignumeric_as_varchar = false;
SELECT typeof(b) AS t_bignum, b FROM bigquery_query('__DATA_PROJECT__',
  $$SELECT CAST('1.23' AS BIGNUMERIC) AS b$$,
  billing_project := '__BILLING__', use_rest_api := true);
