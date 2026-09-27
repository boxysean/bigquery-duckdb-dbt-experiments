-- T05: do WHERE predicates reach BigQuery?
-- bq_debug_show_queries = true prints the projection and the row restriction that
-- were handed to the Storage Read API. The lines starting "BigQuery selected
-- fields:" / "BigQuery row restrictions:" are the evidence; the count is only a
-- sanity check that the answer is right.
LOAD bigquery;
CREATE SECRET bq_pub (TYPE bigquery, SCOPE 'bq://__DATA_PROJECT__',
                      SERVICE_ACCOUNT_PATH '__SA_PATH__');
SET bq_debug_show_queries = true;
SELECT count(*) AS ca_since_2000
FROM bigquery_scan('__DATA_PROJECT__.usa_names.usa_1910_2013',
                   billing_project := '__BILLING__')
WHERE state = 'CA' AND year >= 2000;
