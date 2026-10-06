-- Grain: one row per user, including users who never ordered (zero totals,
-- null first/last order).
with users as (

    select user_id
    from {{ ref('stg_thelook__users') }}

),

order_totals as (

    select
        user_id,
        min(order_created_at)       as first_order_at,
        max(order_created_at)       as last_order_at,
        count(*)                    as lifetime_orders,
        sum(item_count)             as lifetime_items,
        sum(gross_revenue)          as lifetime_gross_revenue,
        sum(total_cost)             as lifetime_total_cost,
        sum(gross_margin)           as lifetime_gross_margin,
        sum(returned_item_count)    as lifetime_returned_items
    from {{ ref('int_orders__item_rollup') }}
    group by user_id

)

select
    users.user_id,
    order_totals.first_order_at,
    order_totals.last_order_at,
    cast(coalesce(order_totals.lifetime_orders, 0) as {{ int_type() }})                           as lifetime_orders,
    cast(coalesce(order_totals.lifetime_items, 0) as {{ int_type() }})                            as lifetime_items,
    cast(coalesce(order_totals.lifetime_gross_revenue, 0) as {{ money_type() }})        as lifetime_gross_revenue,
    cast(coalesce(order_totals.lifetime_total_cost, 0) as {{ money_type() }})           as lifetime_total_cost,
    cast(coalesce(order_totals.lifetime_gross_margin, 0) as {{ money_type() }})         as lifetime_gross_margin,
    cast(coalesce(order_totals.lifetime_returned_items, 0) as {{ int_type() }})                   as lifetime_returned_items
from users
left join order_totals
    on order_totals.user_id = users.user_id
