-- b26: the reverse direction, step 1 — DuckDB writes Parquet. A deterministic 1,000-row
-- table carrying the types a warehouse actually has to move: DECIMAL(38,9) at full width,
-- DOUBLE, VARCHAR with non-ASCII text, BOOLEAN, DATE, TIMESTAMP, TIMESTAMPTZ, BLOB, a
-- list, a struct, and a list of structs. Every 100th row is NULL in the nullable columns.
--
-- One DuckDB trap is visible in how `n` is built: DECIMAL / DECIMAL returns DOUBLE in
-- DuckDB, so a decimal column produced by division silently becomes a FLOAT64 (and then a
-- BigQuery FLOAT64) — the first version of this scenario did exactly that. Building the
-- value from its integer and fractional text keeps it a real DECIMAL(38,9).
CREATE TABLE reverse_src AS
SELECT
  i AS id,
  CASE WHEN i % 100 = 0 THEN NULL
       ELSE CAST((12345678901234567890123456789 + i)::VARCHAR || '.123456789' AS DECIMAL(38,9))
  END AS n,
  CASE WHEN i % 100 = 0 THEN NULL ELSE CAST(i AS DOUBLE) * 1.5 END AS d,
  CASE WHEN i % 100 = 0 THEN NULL ELSE 'row-' || i::VARCHAR || '-héllo → wörld' END AS s,
  (i % 2 = 0) AS b,
  DATE '2024-01-02' + CAST(i % 30 AS INTEGER) AS dt,
  TIMESTAMP '2024-01-02 03:04:05.678901' + CAST(i % 60 AS INTEGER) * INTERVAL '1 second' AS ts,
  TIMESTAMPTZ '2024-01-02 03:04:05.678901+00' + CAST(i % 60 AS INTEGER) * INTERVAL '1 second' AS tstz,
  CASE WHEN i % 100 = 0 THEN NULL ELSE CAST('abc-' || i::VARCHAR AS BLOB) END AS bin,
  CASE WHEN i % 100 = 0 THEN NULL ELSE [i, i + 1, i + 2] END AS arr_i,
  CASE WHEN i % 100 = 0 THEN NULL ELSE struct_pack(a := i, b := 'x-' || i::VARCHAR) END AS st,
  CASE WHEN i % 100 = 0 THEN NULL ELSE
      [struct_pack(x := i, y := 'y-' || i::VARCHAR), struct_pack(x := i + 1, y := 'z-' || i::VARCHAR)]
  END AS arr_st
FROM range(0, 1000) AS t(i);

DESCRIBE reverse_src;

COPY reverse_src TO '__PARQUET_OUT__' (FORMAT PARQUET);

-- what actually landed in the file: the Parquet physical type and logical type per column
SELECT name, type, converted_type, logical_type, duckdb_type
FROM parquet_schema('__PARQUET_OUT__')
WHERE name IN ('id', 'n', 'd', 'ts', 'tstz', 'arr_i', 'st', 'arr_st');

-- the same rows as text, for the verification step (b29). Decimals, timestamps and the
-- nested values are cast explicitly so the comparison is over values, not formatting.
COPY (
  SELECT id,
         CAST(n AS VARCHAR) AS n,
         CAST(d AS VARCHAR) AS d,
         s,
         CAST(b AS VARCHAR) AS b,
         CAST(dt AS VARCHAR) AS dt,
         CAST(ts AS VARCHAR) AS ts,
         CAST(tstz AS VARCHAR) AS tstz,
         hex(bin) AS bin,
         CAST(arr_i AS VARCHAR) AS arr_i,
         to_json(st) AS st,
         to_json(arr_st) AS arr_st
  FROM reverse_src ORDER BY id
) TO '__DUMP_OUT__' (FORMAT CSV, HEADER, NULL '\N');

SELECT count(*) AS rows_written, min(id) AS min_id, max(id) AS max_id,
       sum(CASE WHEN n IS NULL THEN 1 ELSE 0 END) AS null_n
FROM reverse_src;
