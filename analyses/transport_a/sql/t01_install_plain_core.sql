-- T01: is there a CORE-repo build of the bigquery extension?
-- The driver runs this with HOME pointed at an empty directory, so nothing is
-- cached and DuckDB has to ask the core repository (extensions.duckdb.org).
-- Expectation from the card: HTTP 404 -- bigquery is not a core extension.
INSTALL bigquery;
SELECT extension_name, installed, installed_from
FROM duckdb_extensions() WHERE extension_name = 'bigquery';
