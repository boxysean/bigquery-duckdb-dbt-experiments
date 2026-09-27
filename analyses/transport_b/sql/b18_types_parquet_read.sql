-- b18: the nested/repeated export read back. This is the half of the type story that CSV
-- cannot carry at all: arrays, structs, arrays of structs and nested structs.
CREATE SECRET tb_http (TYPE http, BEARER_TOKEN '__TOKEN__');
DESCRIBE SELECT * FROM read_parquet(__URLS__);
SELECT * FROM read_parquet(__URLS__) ORDER BY id;
