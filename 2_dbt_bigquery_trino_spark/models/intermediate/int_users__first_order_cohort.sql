-- Grain: one row per user. A user with no order has a null first_order_at and
-- cohort_month (they belong to no cohort).
with users as (

    select user_id, created_at
    from {{ ref('stg_thelook__users') }}

),

first_orders as (

    select user_id, min(created_at) as first_order_at
    from {{ ref('stg_thelook__orders') }}
    group by user_id

)

select
    users.user_id,
    users.created_at                                    as signup_at,
    first_orders.first_order_at,
    {{ month_start('first_orders.first_order_at') }}    as cohort_month
from users
left join first_orders
    on first_orders.user_id = users.user_id
