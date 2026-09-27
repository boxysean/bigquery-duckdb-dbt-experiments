-- b07: the read route that works on this box — an OAuth bearer token on an `http`
-- secret, against the GCS XML API object URL. __TOKEN__ is substituted at run time and
-- scrubbed from the logs; the token is a one-hour access token for the service account.
CREATE SECRET tb_http (TYPE http, BEARER_TOKEN '__TOKEN__');
SELECT count(*) AS n,
       sum(customer_count) AS customers,
       sum(gross_revenue) AS revenue
FROM read_parquet('https://storage.googleapis.com/__BUCKET__/__PREFIX__/b02/mart_daily_revenue-000000000000.parquet');
