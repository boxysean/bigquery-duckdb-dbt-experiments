-- T03: the secret-scope trap, in both directions.
-- A secret is selected by the project it is SCOPEd to. Scope it to the project
-- that PAYS and an operation against the project that HOLDS THE DATA falls back
-- to ADC (and, on this box, to a lookup of the GCE metadata server).
LOAD bigquery;
CREATE SECRET wrong_scope (TYPE bigquery, SCOPE 'bq://__BILLING__',
                           SERVICE_ACCOUNT_PATH '__SA_PATH__');

-- (a) secret scoped to the billing project, data in the public project
SELECT 'a: scan of public data with a billing-scoped secret' AS case,
       count(*) AS n
FROM bigquery_scan('__DATA_PROJECT__.usa_names.usa_1910_2013',
                   billing_project := '__BILLING__')
WHERE state = 'CA';

-- (b) secret scoped to the data project, job submitted against the billing project
SELECT 'b: job in the billing project with a data-scoped secret' AS case,
       count(*) AS n
FROM bigquery_query('__BILLING__', 'SELECT 1 AS one');
