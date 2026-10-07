{#
  Date and time arithmetic. Every *_at column from staging up is a naive UTC
  timestamp_type() (see to_utc_timestamp), so "the day" and "the month" below
  are UTC ones.
#}

{#
  date_diff_days(later, earlier): whole days from earlier to later (positive when
  later is after earlier), for DATE arguments. Both engines call it DATE_DIFF but
  the arguments are REVERSED: DuckDB takes the part first as a quoted string and
  subtracts start from end, `date_diff('day', <earlier>, <later>)`; BigQuery takes
  the part last as a bare keyword and subtracts the second from the first,
  `date_diff(<later>, <earlier>, day)`.
#}
{% macro date_diff_days(later_expr, earlier_expr) -%}
    {{ return(adapter.dispatch('date_diff_days', 'bq_duckdb_experiments')(later_expr, earlier_expr)) }}
{%- endmacro %}

{% macro default__date_diff_days(later_expr, earlier_expr) -%}
    date_diff('day', {{ earlier_expr }}, {{ later_expr }})
{%- endmacro %}

{% macro bigquery__date_diff_days(later_expr, earlier_expr) -%}
    date_diff({{ later_expr }}, {{ earlier_expr }}, day)
{%- endmacro %}

{#
  format_date_str(expr, fmt): a date as text using strftime-style %-codes (the
  common codes %Y %m %d %j %a %b mean the same on both engines). DuckDB has
  STRFTIME(<expr>, '<fmt>'), value first; BigQuery has FORMAT_DATE('<fmt>',
  <expr>), format FIRST, and no STRFTIME. On BigQuery expr must be a DATE
  (FORMAT_DATE does not take a TIMESTAMP); DuckDB accepts a DATE or a TIMESTAMP.
  fmt is a plain string; the macro quotes it.
#}
{% macro format_date_str(expr, fmt) -%}
    {{ return(adapter.dispatch('format_date_str', 'bq_duckdb_experiments')(expr, fmt)) }}
{%- endmacro %}

{% macro default__format_date_str(expr, fmt) -%}
    strftime({{ expr }}, '{{ fmt }}')
{%- endmacro %}

{% macro bigquery__format_date_str(expr, fmt) -%}
    format_date('{{ fmt }}', {{ expr }})
{%- endmacro %}

{#
  format_month(expr): 'YYYY-MM', the one date format the marts need. Same split
  as format_date_str: DuckDB `strftime(<expr>, '%Y-%m')`, BigQuery
  `format_date('%Y-%m', <expr>)` (a DATE on BigQuery).
#}
{% macro format_month(expr) -%}
    {{ return(adapter.dispatch('format_month', 'bq_duckdb_experiments')(expr)) }}
{%- endmacro %}

{% macro default__format_month(expr) -%}
    {{ format_date_str(expr, '%Y-%m') }}
{%- endmacro %}

{% macro bigquery__format_month(expr) -%}
    {{ format_date_str(expr, '%Y-%m') }}
{%- endmacro %}

{#
  timestamp_trunc_to(expr, granularity): truncate a timestamp to the start of its
  second|minute|hour|day|week|month|quarter|year. BigQuery has TIMESTAMP_TRUNC
  with the part as a bare keyword, `timestamp_trunc(<expr>, month)`; DuckDB has
  only DATE_TRUNC with the part as a quoted string, `date_trunc('month', <expr>)`.
  Weeks start on MONDAY on both: DuckDB's 'week' is the ISO week, BigQuery's bare
  WEEK starts on Sunday, so the BigQuery branch renders WEEK(MONDAY). Any other
  granularity is a compiler error.
#}
{% macro timestamp_trunc_to(expr, granularity) -%}
    {%- set allowed = ['second', 'minute', 'hour', 'day', 'week', 'month', 'quarter', 'year'] -%}
    {%- if granularity is not string or (granularity | lower) not in allowed -%}
        {{ exceptions.raise_compiler_error(
            "timestamp_trunc_to(expr, granularity): granularity must be one of "
            ~ allowed | join('|') ~ ", got '" ~ granularity ~ "'") }}
    {%- endif -%}
    {{ return(adapter.dispatch('timestamp_trunc_to', 'bq_duckdb_experiments')(expr, granularity | lower)) }}
{%- endmacro %}

{% macro default__timestamp_trunc_to(expr, granularity) -%}
    date_trunc('{{ granularity }}', {{ expr }})
{%- endmacro %}

{% macro bigquery__timestamp_trunc_to(expr, granularity) -%}
    timestamp_trunc({{ expr }}, {{ 'week(monday)' if granularity == 'week' else granularity }})
{%- endmacro %}

{#
  day_of_week_iso(expr): ISO day of week, Monday = 1 .. Sunday = 7. DuckDB's
  `extract(isodow from <expr>)` is already ISO. BigQuery only has DAYOFWEEK,
  numbered Sunday = 1 .. Saturday = 7, and no % operator, so the BigQuery branch
  shifts it: `mod(extract(dayofweek from <expr>) + 5, 7) + 1`
  (Sun 1 -> 7, Mon 2 -> 1, Fri 6 -> 5, Sat 7 -> 6).
#}
{% macro day_of_week_iso(expr) -%}
    {{ return(adapter.dispatch('day_of_week_iso', 'bq_duckdb_experiments')(expr)) }}
{%- endmacro %}

{% macro default__day_of_week_iso(expr) -%}
    extract(isodow from {{ expr }})
{%- endmacro %}

{% macro bigquery__day_of_week_iso(expr) -%}
    (mod(extract(dayofweek from {{ expr }}) + 5, 7) + 1)
{%- endmacro %}

{#
  month_start(expr): the first instant of expr's calendar month, as a naive
  timestamp_type(). expr is a naive UTC timestamp, so this is the UTC month.
  Both branches are timestamp_trunc_to(expr, 'month'); DuckDB's DATE_TRUNC also
  needs the cast back to TIMESTAMP (it returns a DATE for a DATE input), while
  BigQuery's TIMESTAMP_TRUNC already returns a TIMESTAMP.
#}
{% macro month_start(expr) -%}
    {{ return(adapter.dispatch('month_start', 'bq_duckdb_experiments')(expr)) }}
{%- endmacro %}

{% macro default__month_start(expr) -%}
    cast({{ timestamp_trunc_to(expr, 'month') }} as {{ timestamp_type() }})
{%- endmacro %}

{% macro bigquery__month_start(expr) -%}
    {{ timestamp_trunc_to(expr, 'month') }}
{%- endmacro %}

{#
  month_number(expr): yyyymm as an integer (e.g. 202403). Used as a surrogate-key
  part instead of a month timestamp, because integers render as the same text on
  both engines and timestamps do not. EXTRACT(YEAR/MONTH FROM ...) is spelt the
  same on both engines, so the two branches are identical; the dispatch is kept
  so the seam has one shape.
#}
{% macro month_number(expr) -%}
    {{ return(adapter.dispatch('month_number', 'bq_duckdb_experiments')(expr)) }}
{%- endmacro %}

{% macro default__month_number(expr) -%}
    (extract(year from {{ expr }}) * 100 + extract(month from {{ expr }}))
{%- endmacro %}

{% macro bigquery__month_number(expr) -%}
    (extract(year from {{ expr }}) * 100 + extract(month from {{ expr }}))
{%- endmacro %}

{#
  seconds_between(start, end): end - start in seconds, as float_type()
  (microsecond precision). DuckDB has DATE_DIFF('microsecond', <start>, <end>)
  (part first, quoted, start before end); BigQuery needs TIMESTAMP_DIFF(<end>,
  <start>, microsecond) (end first, bare part), because its DATE_DIFF takes DATEs.
#}
{% macro seconds_between(start_expr, end_expr) -%}
    {{ return(adapter.dispatch('seconds_between', 'bq_duckdb_experiments')(start_expr, end_expr)) }}
{%- endmacro %}

{% macro default__seconds_between(start_expr, end_expr) -%}
    cast(date_diff('microsecond', {{ start_expr }}, {{ end_expr }}) as {{ float_type() }}) / 1000000.0
{%- endmacro %}

{% macro bigquery__seconds_between(start_expr, end_expr) -%}
    cast(timestamp_diff({{ end_expr }}, {{ start_expr }}, microsecond) as {{ float_type() }}) / 1000000.0
{%- endmacro %}
