-- [hand-moved] Worked example (card t_ef8e0090): models/marts/dim_date.sql
-- [hand-moved] moved to DuckDB-only SQL by hand from the macro docstrings in macros/polyglot/.
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
    cross join unnest(cast(generate_series(first_date, last_date, interval 1 day) as date[])) as date_day__unnest(date_day)

)

select
    date_day,
    cast(strftime(date_day, '%Y-%m') as varchar)         as date_month,
    cast(date_trunc('month', cast(date_day as timestamp)) as timestamp)     as month_start_at,
    cast(extract(year from date_day) as bigint)               as year_number,
    cast(extract(month from date_day) as bigint)              as month_of_year,
    cast(extract(day from date_day) as bigint)                as day_of_month,
    cast(extract(isodow from date_day) as bigint)         as day_of_week_iso,
    extract(isodow from date_day) >= 6                              as is_weekend,
    cast(date_diff('day', first_date, date_day) as bigint)
                                                                        as days_since_first_order
from spine
order by date_day
