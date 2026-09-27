-- b17b: the JSON column, after the CSV round trip (b14b). What DuckDB sees on the other
-- side of a CSV file is a VARCHAR that happens to contain JSON text.
CREATE SECRET tb_http (TYPE http, BEARER_TOKEN '__TOKEN__');
CREATE TABLE tb_json_csv AS SELECT * FROM read_csv('__JSON_CSV_URL__', header = true);
SELECT 'csv' AS src, column_name, column_type FROM (DESCRIBE SELECT * FROM tb_json_csv);
SELECT id, j, typeof(j) AS duckdb_type FROM tb_json_csv ORDER BY id;
