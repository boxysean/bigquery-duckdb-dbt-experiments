-- Card t_68bfec9c: the array/struct/JSON renderings, on both targets.
-- One constant row whose columns are the types that differ most between DuckDB and
-- BigQuery, built only from the macro layer (SPEC 7.2) so the same text renders on
-- both. The struct fields carry their types and the JSON goes through to_json_value()
-- because this file is shared, byte for byte, with 2_dbt_bigquery_trino_spark, and
-- Trino needs both (see macros/polyglot/structs.sql and json.sql).
select
    cast(1 as {{ int_type() }}) as id,
    {{ generate_series(1, 3) }} as int_array,
    {{ generate_date_series("date '2024-03-01'", "date '2024-03-03'") }} as date_array,
    {{ struct_literal([['id', '1', int_type()], ['channel', "'web'", string_type()]]) }} as pair_struct,
    {{ to_json_value(struct_literal([['id', '1', int_type()], ['channel', "'web'", string_type()]])) }} as pair_json
