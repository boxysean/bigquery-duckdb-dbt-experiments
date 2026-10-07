{#
  struct_literal(fields): a struct value from [name, sql-expression] pairs, e.g.
  {{ struct_literal([['a', 1], ['b', "'x'"]]) }}. A field may carry an optional
  third element, its type (a type macro's output): [name, expression, type]. Both
  engines here ignore it; it exists because the peer project's Trino has no named
  struct constructor and must spell `cast(row(...) as row(a bigint, ...))`, so the
  shared model passes the types once and renders identically on all three engines. BigQuery's constructor takes
  named fields, `struct(1 as a, 'x' as b)`; DuckDB's struct literal is map-like,
  `{'a': 1, 'b': 'x'}`, with the field names as quoted keys. Field access is the
  same on both (`s.a`). An empty field list is a compiler error (neither engine
  has a useful empty struct).
#}
{% macro struct_literal(fields) -%}
    {%- if fields is string or fields is not iterable or fields | length == 0 -%}
        {{ exceptions.raise_compiler_error(
            "struct_literal(fields): fields must be a non-empty list of [name, expression] pairs, got " ~ fields) }}
    {%- endif -%}
    {%- for field in fields -%}
        {%- if field is string or field | length not in [2, 3] -%}
            {{ exceptions.raise_compiler_error(
                "struct_literal(fields): every field must be a [name, expression] pair or a [name, expression, type] triple, got " ~ field) }}
        {%- endif -%}
    {%- endfor -%}
    {{ return(adapter.dispatch('struct_literal', 'bq_duckdb_experiments')(fields)) }}
{%- endmacro %}

{% macro default__struct_literal(fields) -%}
    {%- set parts = [] -%}
    {%- for field in fields -%}
        {%- do parts.append("'" ~ field[0] ~ "': " ~ field[1]) -%}
    {%- endfor -%}
    { {{- parts | join(', ') -}} }
{%- endmacro %}

{% macro bigquery__struct_literal(fields) -%}
    {%- set parts = [] -%}
    {%- for field in fields -%}
        {%- do parts.append(field[1] ~ " as " ~ field[0]) -%}
    {%- endfor -%}
    struct({{ parts | join(', ') }})
{%- endmacro %}
