{#
  Date and time arithmetic. Every *_at column from staging up is a naive UTC
  timestamp_type() (see to_utc_timestamp), so "the day" and "the month" below are UTC.
#}

{#
  date_diff_days(later, earlier): whole days from earlier to later, for DATEs. Both
  engines call it DATE_DIFF with REVERSED arguments: Trino takes the unit first as a
  quoted string, `date_diff('day', <earlier>, <later>)`; BigQuery takes it last as a
  bare keyword, `date_diff(<later>, <earlier>, day)`.
#}
{% macro date_diff_days(later_expr, earlier_expr) -%}
    {{ return(adapter.dispatch('date_diff_days', 'bq_trino_experiments')(later_expr, earlier_expr)) }}
{%- endmacro %}

{% macro trino__date_diff_days(later_expr, earlier_expr) -%}
    date_diff('day', {{ earlier_expr }}, {{ later_expr }})
{%- endmacro %}

{% macro bigquery__date_diff_days(later_expr, earlier_expr) -%}
    date_diff({{ later_expr }}, {{ earlier_expr }}, day)
{%- endmacro %}

{#
  format_date_str(expr, fmt): a date as text using %-codes. Trino's DATE_FORMAT uses
  MySQL-style codes, which agree with BigQuery's strftime-style codes for the common
  %Y %m %d %j %a %b (but NOT everywhere: e.g. Trino %i is minutes, %M a month NAME).
  BigQuery FORMAT_DATE('<fmt>', <date>) puts the format first; Trino
  DATE_FORMAT(<timestamp>, '<fmt>') puts it last and wants a timestamp, so the Trino
  branch casts. Do not confuse it with Spark's date_format, which takes Java patterns.
#}
{% macro format_date_str(expr, fmt) -%}
    {{ return(adapter.dispatch('format_date_str', 'bq_trino_experiments')(expr, fmt)) }}
{%- endmacro %}

{% macro trino__format_date_str(expr, fmt) -%}
    date_format(cast({{ expr }} as timestamp(6)), '{{ fmt }}')
{%- endmacro %}

{% macro bigquery__format_date_str(expr, fmt) -%}
    format_date('{{ fmt }}', {{ expr }})
{%- endmacro %}

{#
  format_month(expr): 'YYYY-MM'.
#}
{% macro format_month(expr) -%}
    {{ return(adapter.dispatch('format_month', 'bq_trino_experiments')(expr)) }}
{%- endmacro %}

{% macro trino__format_month(expr) -%}
    {{ format_date_str(expr, '%Y-%m') }}
{%- endmacro %}

{% macro bigquery__format_month(expr) -%}
    {{ format_date_str(expr, '%Y-%m') }}
{%- endmacro %}

{#
  timestamp_trunc_to(expr, granularity): truncate to second|minute|hour|day|week|month|
  quarter|year. BigQuery TIMESTAMP_TRUNC with a bare keyword; Trino DATE_TRUNC with a
  quoted unit. Weeks start on MONDAY on both: Trino's 'week' is the ISO week, BigQuery's
  bare WEEK starts on Sunday, so the BigQuery branch renders WEEK(MONDAY).
#}
{% macro timestamp_trunc_to(expr, granularity) -%}
    {%- set allowed = ['second', 'minute', 'hour', 'day', 'week', 'month', 'quarter', 'year'] -%}
    {%- if granularity is not string or (granularity | lower) not in allowed -%}
        {{ exceptions.raise_compiler_error(
            "timestamp_trunc_to(expr, granularity): granularity must be one of "
            ~ allowed | join('|') ~ ", got '" ~ granularity ~ "'") }}
    {%- endif -%}
    {{ return(adapter.dispatch('timestamp_trunc_to', 'bq_trino_experiments')(expr, granularity | lower)) }}
{%- endmacro %}

{% macro trino__timestamp_trunc_to(expr, granularity) -%}
    date_trunc('{{ granularity }}', {{ expr }})
{%- endmacro %}

{% macro bigquery__timestamp_trunc_to(expr, granularity) -%}
    timestamp_trunc({{ expr }}, {{ 'week(monday)' if granularity == 'week' else granularity }})
{%- endmacro %}

{#
  day_of_week_iso(expr): ISO day of week, Monday = 1 .. Sunday = 7. Trino's
  DAY_OF_WEEK is already ISO. BigQuery's DAYOFWEEK is Sunday = 1 .. Saturday = 7, so the
  BigQuery branch shifts it.
#}
{% macro day_of_week_iso(expr) -%}
    {{ return(adapter.dispatch('day_of_week_iso', 'bq_trino_experiments')(expr)) }}
{%- endmacro %}

{% macro trino__day_of_week_iso(expr) -%}
    day_of_week({{ expr }})
{%- endmacro %}

{% macro bigquery__day_of_week_iso(expr) -%}
    (mod(extract(dayofweek from {{ expr }}) + 5, 7) + 1)
{%- endmacro %}

{#
  month_start(expr): the first instant of expr's month, as a naive timestamp_type().
  Trino's DATE_TRUNC keeps the input type (a DATE stays a DATE), so the cast pins it.
#}
{% macro month_start(expr) -%}
    {{ return(adapter.dispatch('month_start', 'bq_trino_experiments')(expr)) }}
{%- endmacro %}

{% macro trino__month_start(expr) -%}
    cast({{ timestamp_trunc_to(expr, 'month') }} as {{ timestamp_type() }})
{%- endmacro %}

{% macro bigquery__month_start(expr) -%}
    {{ timestamp_trunc_to(expr, 'month') }}
{%- endmacro %}

{#
  month_number(expr): yyyymm as an integer (e.g. 202403). EXTRACT is spelt the same on
  both engines; the dispatch is kept so the seam has one shape.
#}
{% macro month_number(expr) -%}
    {{ return(adapter.dispatch('month_number', 'bq_trino_experiments')(expr)) }}
{%- endmacro %}

{% macro trino__month_number(expr) -%}
    (extract(year from {{ expr }}) * 100 + extract(month from {{ expr }}))
{%- endmacro %}

{% macro bigquery__month_number(expr) -%}
    (extract(year from {{ expr }}) * 100 + extract(month from {{ expr }}))
{%- endmacro %}

{#
  seconds_between(start, end): end - start in seconds, as float_type(), to the
  microsecond.

  Trino has no microsecond unit in DATE_DIFF (its finest is 'millisecond'), and
  subtracting timestamps gives an INTERVAL DAY TO SECOND, which is millisecond
  precision. TO_UNIXTIME returns epoch seconds as a DOUBLE including the fraction, so
  the difference keeps microseconds; ROUND(.., 6) removes the double's last-bit noise
  (a double holds ~15.9 significant digits; epoch seconds at microsecond resolution
  need 16). BigQuery: TIMESTAMP_DIFF in microseconds.
#}
{% macro seconds_between(start_expr, end_expr) -%}
    {{ return(adapter.dispatch('seconds_between', 'bq_trino_experiments')(start_expr, end_expr)) }}
{%- endmacro %}

{% macro trino__seconds_between(start_expr, end_expr) -%}
    round(to_unixtime({{ end_expr }}) - to_unixtime({{ start_expr }}), 6)
{%- endmacro %}

{% macro bigquery__seconds_between(start_expr, end_expr) -%}
    cast(timestamp_diff({{ end_expr }}, {{ start_expr }}, microsecond) as {{ float_type() }}) / 1000000.0
{%- endmacro %}
