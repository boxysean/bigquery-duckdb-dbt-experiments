{#
  struct_literal(fields): a struct value from [name, sql-expression] pairs, e.g.
  {{ struct_literal([['a', 1], ['b', "'x'"]]) }}. The two engines AGREE: both
  take named fields, `struct(1 as a, 'x' as b)`, and field access is `s.a` on
  both (measured on Spark 4.2.0). Both branches render the same thing; the
  dispatch is kept so the seam has one shape. An empty field list is a compiler
  error (neither engine has a useful empty struct).
#}
{% macro struct_literal(fields) -%}
    {%- if fields is string or fields is not iterable or fields | length == 0 -%}
        {{ exceptions.raise_compiler_error(
            "struct_literal(fields): fields must be a non-empty list of [name, expression] pairs, got " ~ fields) }}
    {%- endif -%}
    {%- for field in fields -%}
        {%- if field is string or field | length != 2 -%}
            {{ exceptions.raise_compiler_error(
                "struct_literal(fields): every field must be a [name, expression] pair, got " ~ field) }}
        {%- endif -%}
    {%- endfor -%}
    {{ return(adapter.dispatch('struct_literal', 'bq_spark_experiments')(fields)) }}
{%- endmacro %}

{% macro default__struct_literal(fields) -%}
    {%- set parts = [] -%}
    {%- for field in fields -%}
        {%- do parts.append(field[1] ~ " as " ~ field[0]) -%}
    {%- endfor -%}
    struct({{ parts | join(', ') }})
{%- endmacro %}

{% macro bigquery__struct_literal(fields) -%}
    {%- set parts = [] -%}
    {%- for field in fields -%}
        {%- do parts.append(field[1] ~ " as " ~ field[0]) -%}
    {%- endfor -%}
    struct({{ parts | join(', ') }})
{%- endmacro %}
