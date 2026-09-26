{#
  The macro layer's own tests, as run-operations. Neither touches a model.

  polyglot_render(include_bignumeric=false): logs every macro's rendering for the
  current target, one line per invocation:
      render <macro-name> <target.type> :: <rendered sql>
  It never queries the warehouse, so it runs on --target bigquery without
  credentials. include_bignumeric=true also renders decimal_type(77, 38), which
  is `bignumeric` on BigQuery and a compiler error on DuckDB BY DESIGN (the
  decimal ceiling, see decimal_type in types.sql).

      dbt run-operation polyglot_render --target bigquery
      dbt run-operation polyglot_render --args '{include_bignumeric: true}' --target duckdb   # fails
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
    {%- for name, sql in renders -%}
        {%- do log('render ' ~ name ~ ' ' ~ target.type ~ ' :: ' ~ sql, info=true) -%}
    {%- endfor -%}
    {%- if include_bignumeric -%}
        {%- do log('render decimal_type ' ~ target.type ~ ' :: ' ~ decimal_type(77, 38), info=true) -%}
    {%- endif -%}
{% endmacro %}

{#
  polyglot_selfcheck(): runs every macro's DuckDB rendering against DuckDB with
  constant inputs and compares the answer (a value, or typeof() where the type is
  the point). Prints `selfcheck ok  <name>` or
  `selfcheck FAIL <name> expected <x> got <y>`, and raises at the end if any case
  failed. Every value is compared as DuckDB's VARCHAR rendering of it (so a list
  is '[1, 2, 3]'); NULL is compared as none.

  DuckDB only: on any other target it logs that it was skipped and exits 0,
  because BigQuery cannot be executed from this machine (no credentials).
#}
{% macro polyglot_selfcheck() %}
    {%- if target.type != 'duckdb' -%}
        {%- do log('selfcheck skipped: ' ~ target.type ~ ' cannot be executed here (no credentials; render-only)', info=true) -%}
        {{ return('') }}
    {%- endif -%}

    {%- set ts = "timestamp '2024-03-15 13:45:12'" -%}
    {%- set cases = [
        ['safe_cast int value', safe_cast("'42'", int_type()), '42'],
        ['safe_cast int typeof', 'typeof(' ~ safe_cast("'42'", int_type()) ~ ')', 'BIGINT'],
        ['safe_cast failure is null', safe_cast("'nope'", int_type()), none],
        ['safe_divide by zero is null', safe_divide(1, 0), none],
        ['safe_divide value', safe_divide(1, 4), '0.25'],
        ['safe_divide typeof', 'typeof(' ~ safe_divide(1, 4) ~ ')', 'DOUBLE'],
        ['safe_divide decimal typeof', 'typeof(' ~ safe_divide('cast(1 as decimal(18,2))', 'cast(4 as decimal(18,2))') ~ ')', 'DOUBLE'],
        ['date_diff_days', date_diff_days("date '2024-03-15'", "date '2024-03-01'"), '14'],
        ['date_diff_days negative', date_diff_days("date '2024-03-01'", "date '2024-03-15'"), '-14'],
        ['format_month', format_month("timestamp '2024-03-15 13:45:00'"), '2024-03'],
        ['format_date_str', format_date_str("date '2024-03-15'", '%Y/%m/%d'), '2024/03/15'],
        ['timestamp_trunc_to hour', timestamp_trunc_to(ts, 'hour'), '2024-03-15 13:00:00'],
        ['timestamp_trunc_to week is monday', timestamp_trunc_to(ts, 'week'), '2024-03-11 00:00:00'],
        ['timestamp_trunc_to quarter', timestamp_trunc_to(ts, 'quarter'), '2024-01-01 00:00:00'],
        ['day_of_week_iso friday', day_of_week_iso("date '2024-03-15'"), '5'],
        ['day_of_week_iso sunday', day_of_week_iso("date '2024-03-17'"), '7'],
        ['day_of_week_iso monday', day_of_week_iso("date '2024-03-11'"), '1'],
        ['month_start', month_start(ts), '2024-03-01 00:00:00'],
        ['month_start typeof', 'typeof(' ~ month_start(ts) ~ ')', 'TIMESTAMP'],
        ['month_number', month_number(ts), '202403'],
        ['seconds_between', seconds_between(ts, "timestamp '2024-03-15 13:46:42.5'"), '90.5'],
        ['to_string', to_string(42), '42'],
        ['to_utc_timestamp', to_utc_timestamp("timestamptz '2024-03-15 13:45:00+02'"), '2024-03-15 11:45:00'],
        ['to_utc_timestamp typeof', 'typeof(' ~ to_utc_timestamp("timestamptz '2024-03-15 13:45:00+02'") ~ ')', 'TIMESTAMP'],
        ['generate_series', generate_series(1, 5), '[1, 2, 3, 4, 5]'],
        ['generate_series step', generate_series(1, 9, 3), '[1, 4, 7]'],
        ['sum(unnest(generate_series))', '(select sum(x) from unnest(' ~ generate_series(1, 5) ~ ') as t(x))', '15'],
        ['generate_date_series length', 'array_length(' ~ generate_date_series("date '2024-03-01'", "date '2024-03-05'") ~ ')', '5'],
        ['generate_date_series typeof', 'typeof(' ~ generate_date_series("date '2024-03-01'", "date '2024-03-05'") ~ ')', 'DATE[]'],
        ['generate_date_series month step', generate_date_series("date '2024-01-01'", "date '2024-04-01'", '1 month'), '[2024-01-01, 2024-02-01, 2024-03-01, 2024-04-01]'],
        ['unnest_alias names the element', '(select typeof(date_day) from unnest(' ~ generate_date_series("date '2024-03-01'", "date '2024-03-01'") ~ ') as ' ~ unnest_alias('date_day') ~ ')', 'DATE'],
        ['regexp_contains match', regexp_contains("'LifeOS'", "'^Life'"), 'true'],
        ['regexp_contains no match', regexp_contains("'LifeOS'", "'^Nope'"), 'false'],
        ['regexp_contains partial match', regexp_contains("'LifeOS'", "'OS'"), 'true'],
        ['struct_literal', "(select cast(s.a as varchar) || ',' || cast(s.b as varchar) from (select " ~ struct_literal([['a', 1], ['b', 2]]) ~ " as s))", '1,2'],
        ['generate_surrogate_key', generate_surrogate_key(['1', "'x'"]), 'df6729622b8fb993f31b1ba95a27e5cc'],
        ['type_bigint_array', 'typeof(cast([] as ' ~ type_bigint_array() ~ '))', 'BIGINT[]'],
        ['int_type', 'typeof(cast(1 as ' ~ int_type() ~ '))', 'BIGINT'],
        ['string_type', "typeof(cast('x' as " ~ string_type() ~ '))', 'VARCHAR'],
        ['float_type', 'typeof(cast(1 as ' ~ float_type() ~ '))', 'DOUBLE'],
        ['timestamp_type', "typeof(cast('2024-03-15' as " ~ timestamp_type() ~ '))', 'TIMESTAMP'],
        ['money_type', 'typeof(cast(1 as ' ~ money_type() ~ '))', 'DECIMAL(18,2)'],
        ['decimal_type(38, 9)', 'typeof(cast(1 as ' ~ decimal_type(38, 9) ~ '))', 'DECIMAL(38,9)'],
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

    {#- The star modifier is not an expression: check the columns it leaves. -#}
    {%- set result = run_query('select ' ~ except_columns(['b']) ~ ' from (select 1 as a, 2 as b) as t') -%}
    {%- set got = result.column_names | list -%}
    {%- if got == ['a'] -%}
        {%- do log('selfcheck ok  except_columns', info=true) -%}
    {%- else -%}
        {%- do failures.append('except_columns') -%}
        {%- do log('selfcheck FAIL except_columns expected [a] got ' ~ got, info=true) -%}
    {%- endif -%}

    {%- set total = cases | length + 1 -%}
    {%- if failures | length > 0 -%}
        {{ exceptions.raise_compiler_error('polyglot_selfcheck: ' ~ failures | length ~ ' of ' ~ total ~ ' case(s) failed: ' ~ failures | join(', ')) }}
    {%- endif -%}
    {%- do log('selfcheck: all ' ~ total ~ ' cases ok on ' ~ target.type, info=true) -%}
{% endmacro %}
