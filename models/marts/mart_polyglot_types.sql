-- Card t_68bfec9c: the array/struct/JSON renderings, on both targets.
-- One constant row whose columns are the types that differ most between DuckDB and
-- BigQuery, built only from the macro layer (SPEC 7.2) so the same text renders on
-- both. `to_json(...)` is deliberately not a macro: the name and the semantics are
-- identical on both engines, exactly like `unnest(...)` (see macros/polyglot/arrays.sql).
select
    cast(1 as {{ int_type() }}) as id,
    {{ generate_series(1, 3) }} as int_array,
    {{ generate_date_series("date '2024-03-01'", "date '2024-03-03'") }} as date_array,
    {{ struct_literal([['id', '1'], ['channel', "'web'"]]) }} as pair_struct,
    to_json({{ struct_literal([['id', '1'], ['channel', "'web'"]]) }}) as pair_json
