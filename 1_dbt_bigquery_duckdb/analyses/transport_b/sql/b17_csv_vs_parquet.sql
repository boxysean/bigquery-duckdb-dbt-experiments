-- b17: the same rows, exported twice — once as CSV (b15) and once as Parquet (b16).
-- The DESCRIBE pair is the type fidelity question; the SELECT pair is the value question
-- (does NUMERIC survive CSV, and what happens to BIGNUMERIC at full width).
-- JSON is not in this table: Parquet refuses it (b13c) and CSV carries it as text (b17b).
CREATE SECRET tb_http (TYPE http, BEARER_TOKEN '__TOKEN__');
CREATE TABLE tb_from_csv AS SELECT * FROM read_csv('__CSV_URL__', header = true);
CREATE TABLE tb_from_parquet AS SELECT * FROM read_parquet('__PARQUET_URL__');
SELECT 'csv' AS src, column_name, column_type FROM (DESCRIBE SELECT * FROM tb_from_csv)
UNION ALL
SELECT 'parquet' AS src, column_name, column_type FROM (DESCRIBE SELECT * FROM tb_from_parquet)
ORDER BY column_name, src;
SELECT 'csv' AS src, id,
       CAST(n AS VARCHAR) AS n_text, CAST(n_small AS VARCHAR) AS n_small_text,
       CAST(bn AS VARCHAR) AS bn_text, CAST(dt AS VARCHAR) AS dt_text
FROM tb_from_csv ORDER BY id;
SELECT 'parquet' AS src, id,
       CAST(n AS VARCHAR) AS n_text, CAST(n_small AS VARCHAR) AS n_small_text,
       CAST(bn AS VARCHAR) AS bn_text, CAST(dt AS VARCHAR) AS dt_text
FROM tb_from_parquet ORDER BY id;
