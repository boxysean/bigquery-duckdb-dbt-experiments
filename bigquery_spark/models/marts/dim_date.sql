-- Grain: one row per UTC calendar date from the first to the last order date,
-- inclusive (a date spine: days without orders are present).
with bounds as (

    select
        min(order_date)                                                 as first_date,
        max(order_date)                                                 as last_date
    from {{ ref('int_orders__daily') }}

),

spine as (

    select
        date_day,
        first_date
    from bounds
    {{ explode_array_rows(generate_date_series('first_date', 'last_date'), 'date_day') }}

)

select
    date_day,
    cast({{ format_month('date_day') }} as {{ string_type() }})         as date_month,
    {{ month_start('cast(date_day as ' ~ timestamp_type() ~ ')') }}     as month_start_at,
    cast(extract(year from date_day) as {{ int_type() }})               as year_number,
    cast(extract(month from date_day) as {{ int_type() }})              as month_of_year,
    cast(extract(day from date_day) as {{ int_type() }})                as day_of_month,
    cast({{ day_of_week_iso('date_day') }} as {{ int_type() }})         as day_of_week_iso,
    {{ day_of_week_iso('date_day') }} >= 6                              as is_weekend,
    cast({{ date_diff_days('date_day', 'first_date') }} as {{ int_type() }})
                                                                        as days_since_first_order
from spine
order by date_day
