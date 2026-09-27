-- T04: the working form -- SCOPE follows the data, billing_project follows the money.
LOAD bigquery;
CREATE SECRET bq_pub (TYPE bigquery, SCOPE 'bq://__DATA_PROJECT__',
                      SERVICE_ACCOUNT_PATH '__SA_PATH__');
SELECT count(*) AS usa_names_rows
FROM bigquery_scan('__DATA_PROJECT__.usa_names.usa_1910_2013',
                   billing_project := '__BILLING__');
