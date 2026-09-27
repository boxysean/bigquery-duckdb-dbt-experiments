-- Every macro in macros/polyglot/, called once, in one query. Compiled on both
-- targets (dbt compile) so the two renders can be read side by side under
-- target/compiled/.../analyses/; never run. Only macro calls and portable SQL:
-- constant inputs, no source, no ref.
with inputs as (

    select
        date '2024-03-01'                       as first_date,
        date '2024-03-15'                       as date_day,
        timestamp '2024-03-15 13:45:12'         as created_at,
        timestamp '2024-03-15 13:46:42'         as ended_at,
        '42'                                    as raw_number,
        'LifeOS'                                as label

),

showcase as (

    select
        cast(1 as {{ int_type() }})                                         as an_int,
        cast(label as {{ string_type() }})                                  as a_string,
        cast(1.5 as {{ float_type() }})                                     as a_float,
        cast(created_at as {{ timestamp_type() }})                          as a_timestamp,
        cast(9.99 as {{ money_type() }})                                    as a_money,
        cast(1.2345 as {{ decimal_type(18, 4) }})                           as a_decimal,
        cast(null as {{ type_bigint_array() }})                             as an_int_array,
        {{ safe_cast('raw_number', int_type()) }}                           as safe_cast_number,
        {{ to_string('first_date') }}                                       as date_as_text,
        {{ to_utc_timestamp('created_at') }}                                as utc_created_at,
        {{ struct_literal([['a', 1], ['b', 2]]) }}                          as a_struct,
        {{ generate_series(1, 9, 3) }}                                      as int_series,
        {{ generate_date_series('first_date', 'date_day') }}                as date_series,
        {{ date_diff_days('date_day', 'first_date') }}                      as days_since_first,
        {{ format_date_str('date_day', '%Y/%m/%d') }}                       as date_text,
        {{ format_month('date_day') }}                                      as date_month,
        {{ timestamp_trunc_to('created_at', 'hour') }}                      as created_hour,
        {{ day_of_week_iso('date_day') }}                                   as iso_day_of_week,
        {{ month_start('created_at') }}                                     as created_month_start,
        {{ month_number('created_at') }}                                    as created_month_number,
        {{ seconds_between('created_at', 'ended_at') }}                     as seconds_open,
        {{ safe_divide(1, 4) }}                                             as a_quarter,
        {{ regexp_contains('label', "'^Life'") }}                           as label_is_life,
        {{ generate_surrogate_key(['raw_number', 'label']) }}               as a_surrogate_key,
        (select count(*) from unnest({{ generate_series(1, 5) }}) as n)     as unnest_count
    from inputs

)

select {{ except_columns(['an_int_array', 'a_struct']) }}
from showcase
