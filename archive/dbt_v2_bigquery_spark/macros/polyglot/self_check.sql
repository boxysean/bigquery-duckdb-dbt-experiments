{#
  The macro layer's own tests, as run-operations. Neither touches a model.

  polyglot_render(include_bignumeric=false): logs every macro's rendering for the
  current target, one line per invocation:
      render <macro-name> <target.type> :: <rendered sql>
  It never queries the warehouse, so it runs on --target bigquery without
  credentials. include_bignumeric=true also renders decimal_type(77, 38), which
  is `bignumeric` on BigQuery and a compiler error on Spark BY DESIGN (the
  decimal ceiling, see decimal_type in types.sql).

      dbt run-operation polyglot_render --target bigquery
      dbt run-operation polyglot_render --args '{include_bignumeric: true}' --target spark   # fails
#}
{% macro polyglot_render(include_bignumeric=false) %}
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
        ['safe_cast', safe_cast("'42'", int_type())],
        ['to_string', to_string('user_id')],
        ['to_utc_timestamp', to_utc_timestamp('created_at')],
        ['except_columns', except_columns(['a', 'b'])],
        ['struct_literal', struct_literal([['a', 1], ['b', 2]])],
        ['generate_series', generate_series(1, 5)],
        ['generate_series', generate_series(1, 9, 3)],
        ['generate_date_series', generate_date_series("date '2024-03-01'", "date '2024-03-05'")],
        ['generate_date_series', generate_date_series("date '2024-01-01'", "date '2024-12-01'", '1 month')],
        ['generate_date_series', generate_date_series("date '2024-01-01'", "date '2024-12-01'", '1 quarter')],
        ['explode_array_rows', explode_array_rows(generate_date_series('first_date', 'last_date'), 'date_day')],
        ['date_diff_days', date_diff_days('date_day', 'first_date')],
        ['format_date_str', format_date_str('date_day', '%Y/%m/%d')],
        ['format_date_str', format_date_str('created_at', '%j %a %b %H:%M:%S')],
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
    {%- for name, sql in renders -%}
        {%- do log('render ' ~ name ~ ' ' ~ target.type ~ ' :: ' ~ sql, info=true) -%}
    {%- endfor -%}
    {%- if include_bignumeric -%}
        {%- do log('render decimal_type ' ~ target.type ~ ' :: ' ~ decimal_type(77, 38), info=true) -%}
    {%- endif -%}
{% endmacro %}

{#
  polyglot_selfcheck(): runs every macro's rendering for the CURRENT target
  against that target with constant inputs and compares the answer (a value, or
  typeof() where the type is the point). Unlike the root project's, both
  targets here can be executed: Spark through the local Thrift Server, BigQuery
  when a credential is present.

  Every value is fetched as the engine's own STRING rendering of it
  (`cast((<expr>) as string)`), so NULL compares as none and an array compares
  as its text ('[1, 4, 7]' on Spark). Casting to text in SQL is also what lets
  array-valued cases run on Spark at all: dbt-oss 2.0.5's spark adapter cannot
  fetch an ARRAY column ("Unsupported type ARRAY_TYPE"), but it can fetch the
  string.

  Each case carries one expectation PER TARGET. A case that cannot be written
  for one engine says so: its expectation for that target is
  {'skip': '<reason>'}, and it is logged as `selfcheck SKIP <name> (<target>):
  <reason>`. A case with no entry at all for the current target is a compiler
  error, so nothing is ever dropped silently.

  Prints `selfcheck ok  <name>` or `selfcheck FAIL <name> expected <x> got <y>`,
  and raises at the end if any case failed.

      dbt run-operation polyglot_selfcheck --target spark
      dbt run-operation polyglot_selfcheck --target bigquery   # needs a credential
#}
{% macro polyglot_selfcheck() %}
    {%- if target.type not in ['spark', 'bigquery'] -%}
        {{ exceptions.raise_compiler_error('polyglot_selfcheck: this project has two targets, spark and bigquery; got ' ~ target.type) }}
    {%- endif -%}

    {%- set no_typeof = {'skip': 'BigQuery has no typeof() function; the type is not asserted by this self-check on BigQuery'} -%}
    {%- set no_array_text = {'skip': 'BigQuery cannot CAST an ARRAY to STRING; the length/element cases via explode_array_rows cover it'} -%}
    {%- set ts = "timestamp '2024-03-15 13:45:12'" -%}
    {%- set ts_offset = "timestamp '2024-03-15 13:45:00+02:00'" -%}
    {%- set one_row = '(select 1 as one) as base' -%}
    {%- set cases = [
        ['safe_cast int value', safe_cast("'42'", int_type()), {'spark': '42', 'bigquery': '42'}],
        ['safe_cast int typeof', 'typeof(' ~ safe_cast("'42'", int_type()) ~ ')', {'spark': 'bigint', 'bigquery': no_typeof}],
        ['safe_cast failure is null', safe_cast("'nope'", int_type()), {'spark': none, 'bigquery': none}],
        ['safe_divide by zero is null', safe_divide(1, 0), {'spark': none, 'bigquery': none}],
        ['safe_divide value', safe_divide(1, 4), {'spark': '0.25', 'bigquery': '0.25'}],
        ['safe_divide typeof', 'typeof(' ~ safe_divide(1, 4) ~ ')', {'spark': 'double', 'bigquery': no_typeof}],
        ['safe_divide decimal typeof', 'typeof(' ~ safe_divide('cast(1 as decimal(18,2))', 'cast(4 as decimal(18,2))') ~ ')', {'spark': 'double', 'bigquery': no_typeof}],
        ['date_diff_days', date_diff_days("date '2024-03-15'", "date '2024-03-01'"), {'spark': '14', 'bigquery': '14'}],
        ['date_diff_days negative', date_diff_days("date '2024-03-01'", "date '2024-03-15'"), {'spark': '-14', 'bigquery': '-14'}],
        ['format_month', format_month("timestamp '2024-03-15 13:45:00'"), {'spark': '2024-03', 'bigquery': {'skip': 'FORMAT_DATE takes a DATE, not a TIMESTAMP (documented on format_date_str); see format_month date'}}],
        ['format_month date', format_month("date '2024-03-15'"), {'spark': '2024-03', 'bigquery': '2024-03'}],
        ['format_date_str', format_date_str("date '2024-03-15'", '%Y/%m/%d'), {'spark': '2024/03/15', 'bigquery': '2024/03/15'}],
        ['format_date_str every code', format_date_str(ts, '%Y-%m-%d %j %a %b %H:%M:%S'), {'spark': '2024-03-15 075 Fri Mar 13:45:12', 'bigquery': {'skip': 'FORMAT_DATE takes a DATE and has no %H %M %S on a DATE; the time codes are Spark-only here'}}],
        ['timestamp_trunc_to hour', timestamp_trunc_to(ts, 'hour'), {'spark': '2024-03-15 13:00:00', 'bigquery': '2024-03-15 13:00:00+00'}],
        ['timestamp_trunc_to week is monday', timestamp_trunc_to(ts, 'week'), {'spark': '2024-03-11 00:00:00', 'bigquery': '2024-03-11 00:00:00+00'}],
        ['timestamp_trunc_to quarter', timestamp_trunc_to(ts, 'quarter'), {'spark': '2024-01-01 00:00:00', 'bigquery': '2024-01-01 00:00:00+00'}],
        ['day_of_week_iso friday', day_of_week_iso("date '2024-03-15'"), {'spark': '5', 'bigquery': '5'}],
        ['day_of_week_iso sunday', day_of_week_iso("date '2024-03-17'"), {'spark': '7', 'bigquery': '7'}],
        ['day_of_week_iso monday', day_of_week_iso("date '2024-03-11'"), {'spark': '1', 'bigquery': '1'}],
        ['month_start', month_start(ts), {'spark': '2024-03-01 00:00:00', 'bigquery': '2024-03-01 00:00:00+00'}],
        ['month_start typeof', 'typeof(' ~ month_start(ts) ~ ')', {'spark': 'timestamp', 'bigquery': no_typeof}],
        ['month_number', month_number(ts), {'spark': '202403', 'bigquery': '202403'}],
        ['seconds_between', seconds_between(ts, "timestamp '2024-03-15 13:46:42.5'"), {'spark': '90.5', 'bigquery': '90.5'}],
        ['seconds_between keeps microseconds', seconds_between(ts, "timestamp '2024-03-15 13:45:12.000001'"), {'spark': '1.0E-6', 'bigquery': '1e-06'}],
        ['to_string', to_string(42), {'spark': '42', 'bigquery': '42'}],
        ['to_utc_timestamp', to_utc_timestamp(ts_offset), {'spark': '2024-03-15 11:45:00', 'bigquery': '2024-03-15 11:45:00+00'}],
        ['to_utc_timestamp typeof', 'typeof(' ~ to_utc_timestamp(ts_offset) ~ ')', {'spark': 'timestamp', 'bigquery': no_typeof}],
        ['session time zone is UTC', 'current_timezone()', {'spark': 'UTC', 'bigquery': {'skip': 'a BigQuery TIMESTAMP has no session zone in CAST AS STRING (always +00); the zone pin is a Spark concern'}}],
        ['generate_series', generate_series(1, 5), {'spark': '[1, 2, 3, 4, 5]', 'bigquery': no_array_text}],
        ['generate_series step', generate_series(1, 9, 3), {'spark': '[1, 4, 7]', 'bigquery': no_array_text}],
        ['sum(explode_array_rows(generate_series))', '(select sum(x) from ' ~ one_row ~ ' ' ~ explode_array_rows(generate_series(1, 5), 'x') ~ ')', {'spark': '15', 'bigquery': '15'}],
        ['generate_date_series length', '(select count(*) from ' ~ one_row ~ ' ' ~ explode_array_rows(generate_date_series("date '2024-03-01'", "date '2024-03-05'"), 'd') ~ ')', {'spark': '5', 'bigquery': '5'}],
        ['generate_date_series typeof', 'typeof(' ~ generate_date_series("date '2024-03-01'", "date '2024-03-05'") ~ ')', {'spark': 'array<date>', 'bigquery': no_typeof}],
        ['generate_date_series month step', generate_date_series("date '2024-01-01'", "date '2024-04-01'", '1 month'), {'spark': '[2024-01-01, 2024-02-01, 2024-03-01, 2024-04-01]', 'bigquery': no_array_text}],
        ['generate_date_series month step last', '(select max(d) from ' ~ one_row ~ ' ' ~ explode_array_rows(generate_date_series("date '2024-01-01'", "date '2024-04-01'", '1 month'), 'd') ~ ')', {'spark': '2024-04-01', 'bigquery': '2024-04-01'}],
        ['generate_date_series quarter step', '(select count(*) from ' ~ one_row ~ ' ' ~ explode_array_rows(generate_date_series("date '2024-01-01'", "date '2024-07-01'", '1 quarter'), 'd') ~ ')', {'spark': '3', 'bigquery': '3'}],
        ['explode_array_rows names the element', '(select max(date_day) from ' ~ one_row ~ ' ' ~ explode_array_rows(generate_date_series("date '2024-03-01'", "date '2024-03-01'"), 'date_day') ~ ')', {'spark': '2024-03-01', 'bigquery': '2024-03-01'}],
        ['explode_array_rows element typeof', '(select max(typeof(date_day)) from ' ~ one_row ~ ' ' ~ explode_array_rows(generate_date_series("date '2024-03-01'", "date '2024-03-01'"), 'date_day') ~ ')', {'spark': 'date', 'bigquery': no_typeof}],
        ['regexp_contains match', regexp_contains("'LifeOS'", "'^Life'"), {'spark': 'true', 'bigquery': 'true'}],
        ['regexp_contains no match', regexp_contains("'LifeOS'", "'^Nope'"), {'spark': 'false', 'bigquery': 'false'}],
        ['regexp_contains partial match', regexp_contains("'LifeOS'", "'OS'"), {'spark': 'true', 'bigquery': 'true'}],
        ['struct_literal', '(select cast(s.a as ' ~ string_type() ~ ") || ',' || cast(s.b as " ~ string_type() ~ ') from (select ' ~ struct_literal([['a', 1], ['b', 2]]) ~ ' as s) as t)', {'spark': '1,2', 'bigquery': '1,2'}],
        ['generate_surrogate_key', generate_surrogate_key(['1', "'x'"]), {'spark': 'df6729622b8fb993f31b1ba95a27e5cc', 'bigquery': 'df6729622b8fb993f31b1ba95a27e5cc'}],
        ['generate_surrogate_key month_number part', generate_surrogate_key([month_number(ts), '7']), {'spark': 'a480dd56ed1cb8d3a44c245921e9fc0a', 'bigquery': 'a480dd56ed1cb8d3a44c245921e9fc0a'}],
        ['type_bigint_array', 'typeof(cast(array() as ' ~ type_bigint_array() ~ '))', {'spark': 'array<bigint>', 'bigquery': no_typeof}],
        ['int_type', 'typeof(cast(1 as ' ~ int_type() ~ '))', {'spark': 'bigint', 'bigquery': no_typeof}],
        ['string_type', "typeof(cast('x' as " ~ string_type() ~ '))', {'spark': 'string', 'bigquery': no_typeof}],
        ['float_type', 'typeof(cast(1 as ' ~ float_type() ~ '))', {'spark': 'double', 'bigquery': no_typeof}],
        ['timestamp_type', "typeof(cast('2024-03-15' as " ~ timestamp_type() ~ '))', {'spark': 'timestamp', 'bigquery': no_typeof}],
        ['money_type', 'typeof(cast(1 as ' ~ money_type() ~ '))', {'spark': 'decimal(18,2)', 'bigquery': no_typeof}],
        ['money_type rounds to cents', 'cast(1.005 as ' ~ money_type() ~ ')', {'spark': '1.01', 'bigquery': '1.005'}],
        ['decimal_type(38, 9)', 'typeof(cast(1 as ' ~ decimal_type(38, 9) ~ '))', {'spark': 'decimal(38,9)', 'bigquery': no_typeof}],
        ['decimal ceiling: decimal_type(38, 0) is the widest', 'typeof(cast(1 as ' ~ decimal_type(38, 0) ~ '))', {'spark': 'decimal(38,0)', 'bigquery': no_typeof}],
        ['decimal ceiling: decimal_type(77, 38)',
            ('cast(1.5 as ' ~ decimal_type(77, 38) ~ ')') if target.type == 'bigquery' else none,
            {'spark': {'skip': 'decimal_type(77, 38) is a compiler error on Spark BY DESIGN (precision ceiling 38); captured by `dbt run-operation polyglot_render --args "{include_bignumeric: true}" --target spark`'},
             'bigquery': '1.5'}],
    ] -%}

    {%- set failures = [] -%}
    {%- set skipped = [] -%}
    {%- set state = namespace(ok=0) -%}
    {%- for name, expr, expectations in cases -%}
        {%- if target.type not in expectations -%}
            {{ exceptions.raise_compiler_error('polyglot_selfcheck: case "' ~ name ~ '" has no expectation for ' ~ target.type ~ '; give it one or skip it by name') }}
        {%- endif -%}
        {%- set expected = expectations[target.type] -%}
        {%- if expected is mapping -%}
            {%- do skipped.append(name) -%}
            {%- do log('selfcheck SKIP ' ~ name ~ ' (' ~ target.type ~ '): ' ~ expected['skip'], info=true) -%}
        {%- else -%}
            {%- set result = run_query('select cast((' ~ expr ~ ') as ' ~ string_type() ~ ') as v') -%}
            {%- set got = result.rows[0][0] -%}
            {%- if got == expected -%}
                {%- set state.ok = state.ok + 1 -%}
                {%- do log('selfcheck ok  ' ~ name, info=true) -%}
            {%- else -%}
                {%- do failures.append(name) -%}
                {%- do log('selfcheck FAIL ' ~ name ~ ' expected ' ~ expected ~ ' got ' ~ got ~ '   [sql: ' ~ expr ~ ']', info=true) -%}
            {%- endif -%}
        {%- endif -%}
    {%- endfor -%}

    {#- The star modifier is not an expression: check the columns it leaves. -#}
    {%- set result = run_query('select ' ~ except_columns(['b']) ~ ' from (select 1 as a, 2 as b) as t') -%}
    {%- set got = result.column_names | list -%}
    {%- if got == ['a'] -%}
        {%- set state.ok = state.ok + 1 -%}
        {%- do log('selfcheck ok  except_columns', info=true) -%}
    {%- else -%}
        {%- do failures.append('except_columns') -%}
        {%- do log('selfcheck FAIL except_columns expected [a] got ' ~ got, info=true) -%}
    {%- endif -%}

    {%- set total = cases | length + 1 -%}
    {%- if failures | length > 0 -%}
        {{ exceptions.raise_compiler_error('polyglot_selfcheck: ' ~ failures | length ~ ' of ' ~ total ~ ' case(s) failed on ' ~ target.type ~ ': ' ~ failures | join(', ')) }}
    {%- endif -%}
    {%- do log('selfcheck: ' ~ state.ok ~ ' ok, ' ~ skipped | length ~ ' skipped by name, 0 failed, of ' ~ total ~ ' cases on ' ~ target.type
        ~ (' (skipped: ' ~ skipped | join('; ') ~ ')' if skipped | length > 0 else ''), info=true) -%}
{% endmacro %}
