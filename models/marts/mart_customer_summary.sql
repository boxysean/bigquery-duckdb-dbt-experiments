-- Grain: one row per user, including users who never ordered (zero totals,
-- zero months_active, null average_order_value).
with users as (

    select
        user_id,
        cohort_month,
        signup_at,
        first_order_at,
        last_order_at,
        lifetime_orders,
        lifetime_items,
        lifetime_gross_revenue,
        lifetime_gross_margin,
        lifetime_returned_items
    from {{ ref('dim_users') }}

),

active_months as (

    select user_id, count(*) as months_active
    from {{ ref('int_cohorts__user_months') }}
    group by user_id

)

select
    users.user_id,
    users.cohort_month,
    users.signup_at,
    users.first_order_at,
    users.last_order_at,
    cast(coalesce(active_months.months_active, 0) as {{ int_type() }})        as months_active,
    users.lifetime_orders,
    users.lifetime_items,
    users.lifetime_gross_revenue,
    users.lifetime_gross_margin,
    cast(round(users.lifetime_gross_revenue / nullif(users.lifetime_orders, 0), 2)
        as {{ money_type() }})                                      as average_order_value,
    users.lifetime_returned_items                                   as returned_item_count,
    users.lifetime_orders > 1                                       as is_repeat_customer
from users
left join active_months
    on active_months.user_id = users.user_id
