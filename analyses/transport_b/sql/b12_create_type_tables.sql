-- b12: four probe tables in the dbt target dataset. They are split the way the measured
-- behaviour forces them to be split: BigQuery refuses to export JSON to Parquet (b13c),
-- so JSON cannot ride along with the Parquet table, and CSV refuses anything nested
-- (b14), so the nested table cannot ride along with the CSV one.
--   transport_b_types       every type family that survives a Parquet export, plus
--                           arrays, structs, arrays-of-structs and a nested struct
--   transport_b_types_flat  the scalar subset, including BIGNUMERIC, for CSV vs Parquet
--   transport_b_types_json  JSON alone: refused by Parquet (b13c), tried on CSV (b14b)
--   transport_b_types_edge  BIGNUMERIC at full width and GEOGRAPHY, exported on their own
-- Two rows each: one populated, one all-NULL, so NULL handling is measured too.
CREATE OR REPLACE TABLE `__BILLING__.experiments_dev.transport_b_types` AS
SELECT
  1 AS id,
  9007199254740993 AS i64,
  1.5 AS f64,
  NUMERIC '12345678901234567890123456789.123456789' AS n,
  NUMERIC '-0.000000001' AS n_small,
  'héllo → wörld' AS s,
  b'\x01\x02\xff' AS byt,
  TRUE AS b,
  DATE '2024-01-02' AS d,
  DATETIME '2024-01-02 03:04:05.678901' AS dt,
  TIME '03:04:05.678901' AS t,
  TIMESTAMP '2024-01-02 03:04:05.678901+00' AS ts,
  [1, 2, 3] AS arr_i,
  ['a', 'b'] AS arr_s,
  STRUCT(1 AS a, 'x' AS b) AS st,
  [STRUCT(1 AS x, 'y' AS y), STRUCT(2 AS x, 'z' AS z)] AS arr_st,
  STRUCT([STRUCT('q' AS z), STRUCT('r' AS z)] AS inner_list) AS nested
UNION ALL SELECT
  2, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL;

CREATE OR REPLACE TABLE `__BILLING__.experiments_dev.transport_b_types_flat` AS
SELECT
  1 AS id,
  9007199254740993 AS i64,
  1.5 AS f64,
  NUMERIC '12345678901234567890123456789.123456789' AS n,
  NUMERIC '-0.000000001' AS n_small,
  BIGNUMERIC '12345678901234567890123456789012345678.12345678901234567890' AS bn,
  'héllo → wörld' AS s,
  b'\x01\x02\xff' AS byt,
  TRUE AS b,
  DATE '2024-01-02' AS d,
  DATETIME '2024-01-02 03:04:05.678901' AS dt,
  TIME '03:04:05.678901' AS t,
  TIMESTAMP '2024-01-02 03:04:05.678901+00' AS ts
UNION ALL SELECT
  2, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL;

CREATE OR REPLACE TABLE `__BILLING__.experiments_dev.transport_b_types_json` AS
SELECT 1 AS id, JSON '{"k":1,"a":[1,2],"s":"héllo"}' AS j
UNION ALL SELECT 2, NULL;

CREATE OR REPLACE TABLE `__BILLING__.experiments_dev.transport_b_types_edge` AS
SELECT 1 AS id,
  BIGNUMERIC '12345678901234567890123456789012345678.12345678901234567890' AS bn,
  ST_GEOGPOINT(-122.4, 37.7) AS g
UNION ALL SELECT 2, NULL, NULL;

SELECT table_name, column_name, data_type
FROM `__BILLING__.experiments_dev`.INFORMATION_SCHEMA.COLUMNS
WHERE table_name LIKE 'transport_b_types%'
ORDER BY table_name, ordinal_position;
