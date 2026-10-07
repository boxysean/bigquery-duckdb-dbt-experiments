-- Grain: one row per user (every user, including users who never ordered:
-- zero lifetime totals and null first/last order and cohort_month).
with users as (

    select
        user_id,
        first_name,
        last_name,
        email,
        age,
        gender,
        city,
        state,
        country,
        postal_code,
        traffic_source,
        created_at
    from {{ ref('stg_thelook__users') }}

),

cohorts as (

    select user_id, cohort_month
    from {{ ref('int_users__first_order_cohort') }}

),

lifetime as (

    select
        user_id,
        first_order_at,
        last_order_at,
        lifetime_orders,
        lifetime_items,
        lifetime_gross_revenue,
        lifetime_gross_margin,
        lifetime_returned_items
    from {{ ref('int_users__lifetime_orders') }}

)

select
    users.user_id,
    users.first_name,
    users.last_name,
    users.email,
    users.age,
    users.gender,
    users.city,
    users.state,
    users.country,
    users.postal_code,
    users.traffic_source,
    users.created_at                    as signup_at,
    cohorts.cohort_month,
    lifetime.first_order_at,
    lifetime.last_order_at,
    lifetime.lifetime_orders,
    lifetime.lifetime_items,
    lifetime.lifetime_gross_revenue,
    lifetime.lifetime_gross_margin,
    lifetime.lifetime_returned_items
from users
left join cohorts
    on cohorts.user_id = users.user_id
left join lifetime
    on lifetime.user_id = users.user_id
