-- T12c: the probe table from t12/t12b is gone -- checked from BigQuery, not from
-- the catalogue that just dropped it.
LOAD bigquery;
CREATE SECRET bq_me (TYPE bigquery, SCOPE 'bq://__BILLING__',
                     SERVICE_ACCOUNT_PATH '__SA_PATH__');
SELECT count(*) AS probe_tables_left FROM bigquery_query('__BILLING__',
  'SELECT table_name FROM `__BILLING__.experiments_dev.INFORMATION_SCHEMA.TABLES` WHERE table_name = "transport_a_probe"');
SELECT count(*) AS tables_in_experiments_dev FROM bigquery_query('__BILLING__',
  'SELECT table_name FROM `__BILLING__.experiments_dev.INFORMATION_SCHEMA.TABLES`');
