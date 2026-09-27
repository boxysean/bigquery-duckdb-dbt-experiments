-- b14: the documented refusal. "You cannot export nested and repeated data in CSV
-- format." Same table as b13, format CSV. Expected to fail; the error text is the point.
EXPORT DATA OPTIONS(
  uri='gs://__BUCKET__/__PREFIX__/b14/types-*.csv',
  format='CSV',
  overwrite=true) AS
SELECT * FROM `__BILLING__.experiments_dev.transport_b_types`
