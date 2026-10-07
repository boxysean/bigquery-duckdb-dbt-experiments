{#
  The macro layer's own tests, as run-operations. Neither touches a model.

  polyglot_render(): logs every macro's rendering for the current target, one line per
  invocation (`render <macro> <target.type> :: <sql>`). It never queries the warehouse.

      dbt run-operation polyglot_render --target trino
      dbt run-operation polyglot_render --target bigquery     # see scripts/ci_compile.sh

  except_columns is not rendered on Trino: it is a compiler error there by design.
#}
{% macro polyglot_render() %}
    {%- set renders = [
        ['int_type', int_type()],
        ['string_type', string_type()],
        ['float_type', float_type()],
        ['timestamp_type', timestamp_type()],
        ['money_type', money_type()],
        ['decimal_type', decimal_type(18, 4)],
        ['decimal_type', decimal_type(38, 9)],
        ['decimal_type', decimal_type(38, 18)],
        ['type_bigint_array', type_bigint_array()],
        ['geography_type', geography_type()],
        ['physical_layout', physical_layout()],
        ['safe_cast', safe_cast("'42'", int_type())],
        ['to_string', to_string('user_id')],
        ['to_utc_timestamp', to_utc_timestamp('created_at')],
        ['struct_literal', struct_literal([['a', 1, int_type()], ['b', 2, int_type()]])],
        ['to_json_value', to_json_value(struct_literal([['a', 1, int_type()], ['b', 2, int_type()]]))],
        ['generate_series', generate_series(1, 5)],
        ['generate_series', generate_series(1, 9, 3)],
        ['generate_date_series', generate_date_series("date '2024-03-01'", "date '2024-03-05'")],
        ['generate_date_series', generate_date_series("date '2024-01-01'", "date '2024-12-01'", '1 month')],
        ['generate_date_series', generate_date_series("date '2024-01-01'", "date '2024-12-01'", '1 quarter')],
        ['unnest_alias', 'unnest(' ~ generate_date_series('first_date', 'last_date') ~ ') as ' ~ unnest_alias('date_day')],
        ['date_diff_days', date_diff_days('date_day', 'first_date')],
        ['format_date_str', format_date_str('date_day', '%Y/%m/%d')],
        ['format_month', format_month('date_day')],
        ['timestamp_trunc_to', timestamp_trunc_to('created_at', 'hour')],
        ['timestamp_trunc_to', timestamp_trunc_to('created_at', 'week')],
        ['day_of_week_iso', day_of_week_iso('date_day')],
        ['month_start', month_start('created_at')],
        ['month_number', month_number('activity_month')],
        ['seconds_between', seconds_between('started_at', 'ended_at')],
        ['safe_divide', safe_divide('gross_margin', 'gross_revenue')],
        ['regexp_contains', regexp_contains('email', "'^Life'")],
        ['generate_surrogate_key', generate_surrogate_key(['user_id', 'order_id'])],
    ] -%}
    {%- if target.type != 'trino' -%}
        {%- do renders.append(['except_columns', except_columns(['a', 'b'])]) -%}
    {%- endif -%}
    {%- for name, sql in renders -%}
        {%- do log('render ' ~ name ~ ' ' ~ target.type ~ ' :: ' ~ sql, info=true) -%}
    {%- endfor -%}
{% endmacro %}

{#
  polyglot_selfcheck(): EXECUTES every macro's Trino rendering on Trino with constant
  inputs and compares the answer (a value, or typeof() where the type is the point).
  Prints `selfcheck ok  <name>` or `selfcheck FAIL <name> expected <x> got <y>`, and
  raises at the end if any case failed. Values are compared as Trino's VARCHAR
  rendering; arrays and rows, which Trino cannot cast to VARCHAR, through
  json_format(cast(.. as json)).

  The cases mirror project 1's DuckDB self-check one for one where the macro exists on
  both, with the SAME expected values where the answer is engine-independent (dates,
  ISO weekdays, the surrogate key's MD5, seconds to the microsecond). Where the expected
  text differs, it is because Trino renders it differently (timestamp(6) prints six
  fractional digits; type names are lower case), which the case names say.

  Trino only: on BigQuery it logs that it was skipped (no credentials in CI).
#}
{% macro polyglot_selfcheck() %}
    {%- if target.type != 'trino' -%}
        {%- do log('selfcheck skipped: ' ~ target.type ~ ' is render-only here', info=true) -%}
        {{ return('') }}
    {%- endif -%}

    {%- set ts = "timestamp '2024-03-15 13:45:12'" -%}
    {%- set js = "json_format(cast((" -%}
    {%- set je = ") as json))" -%}
    {%- set cases = [
        ['safe_cast int value', safe_cast("'42'", int_type()), '42'],
        ['safe_cast int typeof', 'typeof(' ~ safe_cast("'42'", int_type()) ~ ')', 'bigint'],
        ['safe_cast failure is null', safe_cast("'nope'", int_type()), none],
        ['safe_divide by zero is null', safe_divide(1, 0), none],
        ['safe_divide value (Trino renders a double as 2.5E-1)', safe_divide(1, 4), '2.5E-1'],
        ['safe_divide typeof', 'typeof(' ~ safe_divide(1, 4) ~ ')', 'double'],
        ['safe_divide decimal typeof', 'typeof(' ~ safe_divide('cast(1 as decimal(18,2))', 'cast(4 as decimal(18,2))') ~ ')', 'double'],
        ['date_diff_days', date_diff_days("date '2024-03-15'", "date '2024-03-01'"), '14'],
        ['date_diff_days negative', date_diff_days("date '2024-03-01'", "date '2024-03-15'"), '-14'],
        ['format_month', format_month("timestamp '2024-03-15 13:45:00'"), '2024-03'],
        ['format_month of a date', format_month("date '2024-03-15'"), '2024-03'],
        ['format_date_str', format_date_str("date '2024-03-15'", '%Y/%m/%d'), '2024/03/15'],
        ['format_date_str day of year', format_date_str("date '2024-03-15'", '%j'), '075'],
        ['timestamp_trunc_to hour (6 fractional digits on Trino)', timestamp_trunc_to('cast(' ~ ts ~ ' as timestamp(6))', 'hour'), '2024-03-15 13:00:00.000000'],
        ['timestamp_trunc_to week is monday', timestamp_trunc_to(ts, 'week'), '2024-03-11 00:00:00'],
        ['timestamp_trunc_to quarter', timestamp_trunc_to(ts, 'quarter'), '2024-01-01 00:00:00'],
        ['day_of_week_iso friday', day_of_week_iso("date '2024-03-15'"), '5'],
        ['day_of_week_iso sunday', day_of_week_iso("date '2024-03-17'"), '7'],
        ['day_of_week_iso monday', day_of_week_iso("date '2024-03-11'"), '1'],
        ['month_start', month_start(ts), '2024-03-01 00:00:00.000000'],
        ['month_start typeof', 'typeof(' ~ month_start(ts) ~ ')', 'timestamp(6)'],
        ['month_start of a date', month_start("date '2024-03-15'"), '2024-03-01 00:00:00.000000'],
        ['month_number', month_number(ts), '202403'],
        ['seconds_between (90.5, rendered 9.05E1)', seconds_between(ts, "timestamp '2024-03-15 13:46:42.5'"), '9.05E1'],
        ['seconds_between keeps microseconds', seconds_between("timestamp '2024-03-15 13:45:12.000001'", "timestamp '2024-03-15 13:45:12.000003'"), '2.0E-6'],
        ['seconds_between across years', seconds_between("timestamp '2022-01-01 00:00:00.000001'", "timestamp '2026-01-01 00:00:00.000002'"), '1.26230400000001E8'],
        ['to_string', to_string(42), '42'],
        ['to_utc_timestamp', to_utc_timestamp("timestamp '2024-03-15 13:45:00 +02:00'"), '2024-03-15 11:45:00.000000'],
        ['to_utc_timestamp keeps microseconds', to_utc_timestamp("timestamp '2024-03-15 13:45:00.123456 UTC'"), '2024-03-15 13:45:00.123456'],
        ['to_utc_timestamp typeof', 'typeof(' ~ to_utc_timestamp("timestamp '2024-03-15 13:45:00 +02:00'") ~ ')', 'timestamp(6)'],
        ['generate_series', js ~ generate_series(1, 5) ~ je, '[1,2,3,4,5]'],
        ['generate_series step', js ~ generate_series(1, 9, 3) ~ je, '[1,4,7]'],
        ['generate_series typeof', 'typeof(' ~ generate_series(1, 5) ~ ')', 'array(bigint)'],
        ['sum(unnest(generate_series))', '(select sum(x) from unnest(' ~ generate_series(1, 5) ~ ') as ' ~ unnest_alias('x') ~ ')', '15'],
        ['generate_date_series length', 'cardinality(' ~ generate_date_series("date '2024-03-01'", "date '2024-03-05'") ~ ')', '5'],
        ['generate_date_series typeof', 'typeof(' ~ generate_date_series("date '2024-03-01'", "date '2024-03-05'") ~ ')', 'array(date)'],
        ['generate_date_series month step', js ~ generate_date_series("date '2024-01-01'", "date '2024-04-01'", '1 month') ~ je, '["2024-01-01","2024-02-01","2024-03-01","2024-04-01"]'],
        ['generate_date_series month-end start does not drift', js ~ generate_date_series("date '2024-01-31'", "date '2024-03-31'", '1 month') ~ je, '["2024-01-31","2024-02-29","2024-03-31"]'],
        ['generate_date_series week step', js ~ generate_date_series("date '2024-03-01'", "date '2024-03-15'", '1 week') ~ je, '["2024-03-01","2024-03-08","2024-03-15"]'],
        ['generate_date_series quarter step', 'cardinality(' ~ generate_date_series("date '2024-01-01'", "date '2024-12-01'", '1 quarter') ~ ')', '4'],
        ['generate_date_series value', js ~ generate_date_series("date '2024-03-01'", "date '2024-03-03'") ~ je, '["2024-03-01","2024-03-02","2024-03-03"]'],
        ['unnest_alias names the element', '(select typeof(date_day) from unnest(' ~ generate_date_series("date '2024-03-01'", "date '2024-03-01'") ~ ') as ' ~ unnest_alias('date_day') ~ ')', 'date'],
        ['regexp_contains match', regexp_contains("'LifeOS'", "'^Life'"), 'true'],
        ['regexp_contains no match', regexp_contains("'LifeOS'", "'^Nope'"), 'false'],
        ['regexp_contains partial match', regexp_contains("'LifeOS'", "'OS'"), 'true'],
        ['struct_literal', "(select cast(s.a as varchar) || ',' || cast(s.b as varchar) from (select " ~ struct_literal([['a', 1, int_type()], ['b', 2, int_type()]]) ~ " as s))", '1,2'],
        ['struct_literal typeof', 'typeof(' ~ struct_literal([['a', 1, int_type()], ['b', "'x'", string_type()]]) ~ ')', 'row("a" bigint, "b" varchar)'],
        ['to_json_value value', to_json_value(struct_literal([['a', 1, int_type()], ['b', 2, int_type()]])), '{"a":1,"b":2}'],
        ['to_json_value typeof (varchar: Iceberg has no JSON type)', 'typeof(' ~ to_json_value(struct_literal([['a', 1, int_type()], ['b', 2, int_type()]])) ~ ')', 'varchar'],
        ['generate_surrogate_key (same MD5 as DuckDB and BigQuery)', generate_surrogate_key(['1', "'x'"]), 'df6729622b8fb993f31b1ba95a27e5cc'],
        ['type_bigint_array', 'typeof(cast(array[] as ' ~ type_bigint_array() ~ '))', 'array(bigint)'],
        ['int_type', 'typeof(cast(1 as ' ~ int_type() ~ '))', 'bigint'],
        ['string_type', "typeof(cast('x' as " ~ string_type() ~ '))', 'varchar'],
        ['float_type', 'typeof(cast(1 as ' ~ float_type() ~ '))', 'double'],
        ['timestamp_type (microseconds, not Trino default millis)', "typeof(cast('2024-03-15' as " ~ timestamp_type() ~ '))', 'timestamp(6)'],
        ['money_type (= BigQuery NUMERIC)', 'typeof(cast(1 as ' ~ money_type() ~ '))', 'decimal(38,9)'],
        ['money_type keeps sub-cent digits', 'cast(6.644999999552965e0 as ' ~ money_type() ~ ')', '6.645000000'],
        ['decimal_type(38, 9)', 'typeof(cast(1 as ' ~ decimal_type(38, 9) ~ '))', 'decimal(38,9)'],
        ['geography_type (WKT text on the lakehouse)', 'typeof(cast(null as ' ~ geography_type() ~ '))', 'varchar'],
    ] -%}

    {%- set failures = [] -%}
    {%- for name, expr, expected in cases -%}
        {%- set result = run_query('select cast((' ~ expr ~ ') as varchar) as v') -%}
        {%- set got = result.rows[0][0] -%}
        {%- if got == expected -%}
            {%- do log('selfcheck ok  ' ~ name, info=true) -%}
        {%- else -%}
            {%- do failures.append(name) -%}
            {%- do log('selfcheck FAIL ' ~ name ~ ' expected ' ~ expected ~ ' got ' ~ got ~ '   [sql: ' ~ expr ~ ']', info=true) -%}
        {%- endif -%}
    {%- endfor -%}

    {%- set total = cases | length -%}
    {%- if failures | length > 0 -%}
        {{ exceptions.raise_compiler_error('polyglot_selfcheck: ' ~ failures | length ~ ' of ' ~ total ~ ' case(s) failed: ' ~ failures | join(', ')) }}
    {%- endif -%}
    {%- do log('selfcheck: all ' ~ total ~ ' cases ok on ' ~ target.type, info=true) -%}
{% endmacro %}
