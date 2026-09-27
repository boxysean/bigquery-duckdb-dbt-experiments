-- b24: the evidence for b22/b22b/b22c/b23. One thread and preserve_insertion_order=true so
-- DuckDB hands the file's physical row order back unchanged; then, per file, the sequence
-- of temp (fingerprinted) and how often it goes backwards.
--   A, B, D: three runs of the same SQL with no ORDER BY (b22, b22b, b22c)
--   C:       the same SELECT with ORDER BY temp (b23), which writes one file
-- If the file set were a property of the data, every unordered run would agree on the shard
-- boundaries; if it were sorted, the descents would be 0 in all of them.
SET threads = 1;
SET preserve_insertion_order = true;
CREATE TABLE a1 AS SELECT row_number() OVER () AS rn, stn, temp FROM read_parquet('__A1__');
CREATE TABLE a2 AS SELECT row_number() OVER () AS rn, stn, temp FROM read_parquet('__A2__');
CREATE TABLE b1 AS SELECT row_number() OVER () AS rn, stn, temp FROM read_parquet('__B1__');
CREATE TABLE b2 AS SELECT row_number() OVER () AS rn, stn, temp FROM read_parquet('__B2__');
CREATE TABLE d1 AS SELECT row_number() OVER () AS rn, stn, temp FROM read_parquet('__D1__');
CREATE TABLE d2 AS SELECT row_number() OVER () AS rn, stn, temp FROM read_parquet('__D2__');
CREATE TABLE c1 AS SELECT row_number() OVER () AS rn, stn, temp FROM read_parquet('__C1__');

SELECT 'A (no ORDER BY), file 0' AS src, count(*) AS rows,
       md5(string_agg(temp::VARCHAR, ',' ORDER BY rn)) AS temp_seq_md5 FROM a1
UNION ALL SELECT 'A, file 1', count(*), md5(string_agg(temp::VARCHAR, ',' ORDER BY rn)) FROM a2
UNION ALL SELECT 'B (same SQL, second run), file 0', count(*), md5(string_agg(temp::VARCHAR, ',' ORDER BY rn)) FROM b1
UNION ALL SELECT 'B, file 1', count(*), md5(string_agg(temp::VARCHAR, ',' ORDER BY rn)) FROM b2
UNION ALL SELECT 'D (same SQL, third run), file 0', count(*), md5(string_agg(temp::VARCHAR, ',' ORDER BY rn)) FROM d1
UNION ALL SELECT 'D, file 1', count(*), md5(string_agg(temp::VARCHAR, ',' ORDER BY rn)) FROM d2
UNION ALL SELECT 'C (ORDER BY temp), file 0', count(*), md5(string_agg(temp::VARCHAR, ',' ORDER BY rn)) FROM c1;

SELECT 'A file 0: temp decreases' AS check, count(*) AS n
FROM (SELECT temp, lag(temp) OVER (ORDER BY rn) AS prev FROM a1) WHERE temp < prev
UNION ALL SELECT 'B file 0: temp decreases', count(*)
FROM (SELECT temp, lag(temp) OVER (ORDER BY rn) AS prev FROM b1) WHERE temp < prev
UNION ALL SELECT 'D file 0: temp decreases', count(*)
FROM (SELECT temp, lag(temp) OVER (ORDER BY rn) AS prev FROM d1) WHERE temp < prev
UNION ALL SELECT 'C file 0: temp decreases', count(*)
FROM (SELECT temp, lag(temp) OVER (ORDER BY rn) AS prev FROM c1) WHERE temp < prev;

SELECT 'A file 0: first/last temp' AS check, min(temp) AS lo, max(temp) AS hi FROM a1
UNION ALL SELECT 'C file 0: first/last temp', min(temp), max(temp) FROM c1;
