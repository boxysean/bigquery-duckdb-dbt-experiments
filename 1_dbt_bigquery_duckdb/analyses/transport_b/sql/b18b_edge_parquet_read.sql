-- b18b: BIGNUMERIC (76 significant digits) and GEOGRAPHY, read back from b13b's Parquet.
CREATE SECRET tb_http (TYPE http, BEARER_TOKEN '__TOKEN__');
DESCRIBE SELECT * FROM read_parquet(__URLS__);
SELECT * FROM read_parquet(__URLS__) ORDER BY id;
