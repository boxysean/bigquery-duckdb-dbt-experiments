{#
  Date and time arithmetic. Every *_at column from staging up is a UTC
  timestamp_type() (see to_utc_timestamp), so "the day" and "the month" below
  are UTC ones, on Spark because the session time zone is UTC.
#}

{#
  date_diff_days(later, earlier): whole days from earlier to later (positive when
  later is after earlier), for DATE arguments. BigQuery has DATE_DIFF with the
  part last as a bare keyword, `date_diff(<later>, <earlier>, day)`; Spark has
  DATEDIFF(<later>, <earlier>), days only, no part argument (measured:
  datediff(date '2024-03-15', date '2024-03-01') = 14, reversed = -14). The
  argument ORDER happens to agree; the name and the part argument do not.
#}
{% macro date_diff_days(later_expr, earlier_expr) -%}
    {{ return(adapter.dispatch('date_diff_days', 'bq_spark_experiments')(later_expr, earlier_expr)) }}
{%- endmacro %}

{% macro default__date_diff_days(later_expr, earlier_expr) -%}
    datediff({{ later_expr }}, {{ earlier_expr }})
{%- endmacro %}

{% macro bigquery__date_diff_days(later_expr, earlier_expr) -%}
    date_diff({{ later_expr }}, {{ earlier_expr }}, day)
{%- endmacro %}

{#
  format_date_str(expr, fmt): a date as text. fmt is written ONCE, in the
  project's canonical strftime style, and may use only the codes
  %Y %m %d %j %a %b %H %M %S plus the literal characters - / : . , _ and space;
  anything else is a compiler error on every target, so a format that would
  not translate fails before it reaches either engine.

  This is a genuine incompatibility, not a rename: the FORMAT-STRING LANGUAGE
  differs. BigQuery has FORMAT_DATE('<fmt>', <expr>), format FIRST, with
  strftime %-codes. Spark has DATE_FORMAT(<expr>, '<pattern>'), value first,
  with a Java DateTimeFormatter pattern (measured: date_format(d, 'yyyy/MM/dd')
  works, while '%Y/%m/%d' raises INCONSISTENT_BEHAVIOR_CROSS_VERSION). So the
  Spark branch translates code by code:
      %Y yyyy   %m MM   %d dd   %j DDD   %a EEE   %b MMM
      %H HH     %M mm   %S ss
  (measured: '075 Fri Mar 13 45 12' for 'DDD EEE MMM HH mm ss' on
  2024-03-15 13:45:12). Letters are pattern characters in Java and would need
  quoting, which is why literal letters are refused rather than passed through.
  On BigQuery expr must be a DATE (FORMAT_DATE does not take a TIMESTAMP); Spark
  accepts a DATE or a TIMESTAMP. fmt is a plain string; the macro quotes it.
#}
{% macro format_date_str(expr, fmt) -%}
    {%- set codes = ['Y', 'm', 'd', 'j', 'a', 'b', 'H', 'M', 'S'] -%}
    {%- set literals = ['-', '/', ':', '.', ',', '_', ' '] -%}
    {%- set state = namespace(after_percent=false) -%}
    {%- if fmt is not string or fmt | length == 0 -%}
        {{ exceptions.raise_compiler_error("format_date_str(expr, fmt): fmt must be a non-empty string, got " ~ fmt) }}
    {%- endif -%}
    {%- for ch in fmt -%}
        {%- if state.after_percent -%}
            {%- if ch not in codes -%}
                {{ exceptions.raise_compiler_error(
                    "format_date_str(expr, fmt): unsupported code '%" ~ ch ~ "' in '" ~ fmt
                    ~ "'; only %" ~ codes | join(' %') ~ " translate to a Spark (Java) pattern") }}
            {%- endif -%}
            {%- set state.after_percent = false -%}
        {%- elif ch == '%' -%}
            {%- set state.after_percent = true -%}
        {%- elif ch not in literals -%}
            {{ exceptions.raise_compiler_error(
                "format_date_str(expr, fmt): literal character '" ~ ch ~ "' in '" ~ fmt
                ~ "' is not allowed; only %-codes, spaces and the literals - / : . , _ are portable") }}
        {%- endif -%}
    {%- endfor -%}
    {%- if state.after_percent -%}
        {{ exceptions.raise_compiler_error("format_date_str(expr, fmt): '" ~ fmt ~ "' ends with a lone '%'") }}
    {%- endif -%}
    {{ return(adapter.dispatch('format_date_str', 'bq_spark_experiments')(expr, fmt)) }}
{%- endmacro %}

{% macro default__format_date_str(expr, fmt) -%}
    {%- set java = {'Y': 'yyyy', 'm': 'MM', 'd': 'dd', 'j': 'DDD', 'a': 'EEE', 'b': 'MMM', 'H': 'HH', 'M': 'mm', 'S': 'ss'} -%}
    {%- set state = namespace(after_percent=false, pattern='') -%}
    {%- for ch in fmt -%}
        {%- if state.after_percent -%}
            {%- set state.pattern = state.pattern ~ java[ch] -%}
            {%- set state.after_percent = false -%}
        {%- elif ch == '%' -%}
            {%- set state.after_percent = true -%}
        {%- else -%}
            {%- set state.pattern = state.pattern ~ ch -%}
        {%- endif -%}
    {%- endfor -%}
    date_format({{ expr }}, '{{ state.pattern }}')
{%- endmacro %}

{% macro bigquery__format_date_str(expr, fmt) -%}
    format_date('{{ fmt }}', {{ expr }})
{%- endmacro %}

{#
  format_month(expr): 'YYYY-MM', the one date format the marts need. Both
  branches are format_date_str(expr, '%Y-%m'): Spark
  `date_format(<expr>, 'yyyy-MM')`, BigQuery `format_date('%Y-%m', <expr>)` (a
  DATE on BigQuery).
#}
{% macro format_month(expr) -%}
    {{ return(adapter.dispatch('format_month', 'bq_spark_experiments')(expr)) }}
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
  with the part as a bare keyword, `timestamp_trunc(<expr>, month)`; Spark has
  no TIMESTAMP_TRUNC (measured) and uses DATE_TRUNC with the part as a quoted
  string, `date_trunc('month', <expr>)`, which returns a TIMESTAMP even for a
  DATE input (measured). Weeks start on MONDAY on both: Spark's 'week' is
  already Monday (measured: 2024-03-15 13:45:12 -> 2024-03-11 00:00:00),
  BigQuery's bare WEEK starts on Sunday, so the BigQuery branch renders
  WEEK(MONDAY). Any other granularity is a compiler error.
#}
{% macro timestamp_trunc_to(expr, granularity) -%}
    {%- set allowed = ['second', 'minute', 'hour', 'day', 'week', 'month', 'quarter', 'year'] -%}
    {%- if granularity is not string or (granularity | lower) not in allowed -%}
        {{ exceptions.raise_compiler_error(
            "timestamp_trunc_to(expr, granularity): granularity must be one of "
            ~ allowed | join('|') ~ ", got '" ~ granularity ~ "'") }}
    {%- endif -%}
    {{ return(adapter.dispatch('timestamp_trunc_to', 'bq_spark_experiments')(expr, granularity | lower)) }}
{%- endmacro %}

{% macro default__timestamp_trunc_to(expr, granularity) -%}
    date_trunc('{{ granularity }}', {{ expr }})
{%- endmacro %}

{% macro bigquery__timestamp_trunc_to(expr, granularity) -%}
    timestamp_trunc({{ expr }}, {{ 'week(monday)' if granularity == 'week' else granularity }})
{%- endmacro %}

{#
  day_of_week_iso(expr): ISO day of week, Monday = 1 .. Sunday = 7. Both engines
  number DAYOFWEEK Sunday = 1 .. Saturday = 7, so both shift it the same way,
  (dow + 5) mod 7 + 1 (Sun 1 -> 7, Mon 2 -> 1, Fri 6 -> 5, Sat 7 -> 6). The
  spelling differs: BigQuery has EXTRACT(DAYOFWEEK ...) and no % operator, so
  it uses MOD(); Spark has the DAYOFWEEK() function and % (measured: Fri 5,
  Sun 7, Mon 1).
#}
{% macro day_of_week_iso(expr) -%}
    {{ return(adapter.dispatch('day_of_week_iso', 'bq_spark_experiments')(expr)) }}
{%- endmacro %}

{% macro default__day_of_week_iso(expr) -%}
    ((dayofweek({{ expr }}) + 5) % 7 + 1)
{%- endmacro %}

{% macro bigquery__day_of_week_iso(expr) -%}
    (mod(extract(dayofweek from {{ expr }}) + 5, 7) + 1)
{%- endmacro %}

{#
  month_start(expr): the first instant of expr's calendar month, as a
  timestamp_type(). expr is a UTC timestamp, so this is the UTC month. Both
  branches are timestamp_trunc_to(expr, 'month'), which returns a TIMESTAMP on
  both engines (Spark's DATE_TRUNC does so even for a DATE input, measured), so
  no cast is needed on either.
#}
{% macro month_start(expr) -%}
    {{ return(adapter.dispatch('month_start', 'bq_spark_experiments')(expr)) }}
{%- endmacro %}

{% macro default__month_start(expr) -%}
    {{ timestamp_trunc_to(expr, 'month') }}
{%- endmacro %}

{% macro bigquery__month_start(expr) -%}
    {{ timestamp_trunc_to(expr, 'month') }}
{%- endmacro %}

{#
  month_number(expr): yyyymm as an integer (e.g. 202403). Used as a surrogate-key
  part instead of a month timestamp, because integers render as the same text on
  both engines and timestamps do not. EXTRACT(YEAR/MONTH FROM ...) is spelt the
  same on both engines (measured on Spark: 202403, an int), so the two branches
  are identical; the dispatch is kept so the seam has one shape.
#}
{% macro month_number(expr) -%}
    {{ return(adapter.dispatch('month_number', 'bq_spark_experiments')(expr)) }}
{%- endmacro %}

{% macro default__month_number(expr) -%}
    (extract(year from {{ expr }}) * 100 + extract(month from {{ expr }}))
{%- endmacro %}

{% macro bigquery__month_number(expr) -%}
    (extract(year from {{ expr }}) * 100 + extract(month from {{ expr }}))
{%- endmacro %}

{#
  seconds_between(start, end): end - start in seconds, as float_type()
  (microsecond precision). BigQuery has TIMESTAMP_DIFF(<end>, <start>,
  microsecond). Spark has no TIMESTAMP_DIFF; the Spark branch subtracts
  UNIX_MICROS of each side. Do NOT use UNIX_TIMESTAMP: measured on Spark 4.2.0
  it truncates to whole seconds (90.0 where the answer is 90.5); UNIX_MICROS
  gives 90.5, and 1.0E-6 for a one-microsecond gap.
#}
{% macro seconds_between(start_expr, end_expr) -%}
    {{ return(adapter.dispatch('seconds_between', 'bq_spark_experiments')(start_expr, end_expr)) }}
{%- endmacro %}

{% macro default__seconds_between(start_expr, end_expr) -%}
    cast(unix_micros({{ end_expr }}) - unix_micros({{ start_expr }}) as {{ float_type() }}) / 1000000.0
{%- endmacro %}

{% macro bigquery__seconds_between(start_expr, end_expr) -%}
    cast(timestamp_diff({{ end_expr }}, {{ start_expr }}, microsecond) as {{ float_type() }}) / 1000000.0
{%- endmacro %}
