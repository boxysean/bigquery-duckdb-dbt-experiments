-- T02: the community repository does have it.
-- Same empty HOME as T01, so this is a real download from
-- community-extensions.duckdb.org, not a cache hit.
INSTALL bigquery FROM community;
LOAD bigquery;
SELECT extension_name, install_mode, installed_from, extension_version
FROM duckdb_extensions() WHERE extension_name = 'bigquery';
SELECT version() AS duckdb_version;
