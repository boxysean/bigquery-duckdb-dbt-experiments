-- Grain: one row per user x UTC calendar month in which the user placed at
-- least one order. The activity month is the month of the ORDER's created_at.
with user_order_months as (

    select
        user_id,
        {{ month_start('order_created_at') }}   as activity_month,
        order_id,
        item_count,
        gross_revenue
    from {{ ref('int_orders__item_rollup') }}

),

user_months as (

    select
        user_id,
        activity_month,
        count(*)            as orders,
        sum(item_count)     as items,
        sum(gross_revenue)  as revenue
    from user_order_months
    group by user_id, activity_month

),

cohorts as (

    select user_id, cohort_month
    from {{ ref('int_users__first_order_cohort') }}

)

select
    {{ generate_surrogate_key(['user_months.user_id', month_number('user_months.activity_month')]) }}
                                                        as user_month_key,
    user_months.user_id,
    cohorts.cohort_month,
    user_months.activity_month,
    cast(user_months.orders as bigint)                  as orders,
    cast(user_months.items as bigint)                   as items,
    cast(user_months.revenue as {{ money_type() }})     as revenue
from user_months
left join cohorts
    on cohorts.user_id = user_months.user_id
