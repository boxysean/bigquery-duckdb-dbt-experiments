{#
  struct_literal(fields): a struct value from [name, expression, type] triples, e.g.
  {{ struct_literal([['a', '1', int_type()], ['b', "'x'", string_type()]]) }}.

  BigQuery's constructor takes named fields, `struct(1 as a, 'x' as b)`, and infers the
  types. Trino has no named row constructor: ROW(1, 'x') has anonymous fields, and the
  only way to name them is `cast(row(1, 'x') as row(a bigint, b varchar))`, which needs
  every field's TYPE. So the type is mandatory on Trino (a [name, expression] pair is a
  compiler error there) and ignored on BigQuery. Field access is `s.a` on both, and on
  Spark, which reads the column as a STRUCT.
#}
{% macro struct_literal(fields) -%}
    {%- if fields is string or fields is not iterable or fields | length == 0 -%}
        {{ exceptions.raise_compiler_error(
            "struct_literal(fields): fields must be a non-empty list of [name, expression, type] triples, got " ~ fields) }}
    {%- endif -%}
    {%- for field in fields -%}
        {%- if field is string or field | length not in [2, 3] -%}
            {{ exceptions.raise_compiler_error(
                "struct_literal(fields): every field must be a [name, expression] pair or a [name, expression, type] triple, got " ~ field) }}
        {%- endif -%}
    {%- endfor -%}
    {{ return(adapter.dispatch('struct_literal', 'bq_trino_experiments')(fields)) }}
{%- endmacro %}

{% macro trino__struct_literal(fields) -%}
    {%- set values, types = [], [] -%}
    {%- for field in fields -%}
        {%- if field | length != 3 -%}
            {{ exceptions.raise_compiler_error(
                "struct_literal: field '" ~ field[0] ~ "' has no type. Trino cannot name a ROW field "
                ~ "without casting the whole row to a typed ROW, so every field must be "
                ~ "[name, expression, type], e.g. ['" ~ field[0] ~ "', " ~ field[1] ~ ", int_type()].") }}
        {%- endif -%}
        {%- do values.append(field[1]) -%}
        {%- do types.append(field[0] ~ ' ' ~ field[2]) -%}
    {%- endfor -%}
    cast(row({{ values | join(', ') }}) as row({{ types | join(', ') }}))
{%- endmacro %}

{% macro bigquery__struct_literal(fields) -%}
    {%- set parts = [] -%}
    {%- for field in fields -%}
        {%- do parts.append(field[1] ~ " as " ~ field[0]) -%}
    {%- endfor -%}
    struct({{ parts | join(', ') }})
{%- endmacro %}
