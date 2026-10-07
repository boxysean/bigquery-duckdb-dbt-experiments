-- Grain: one row per order. Starts from stg_thelook__orders so an order with no
-- items would still appear, with zero counts and amounts.
with orders as (

    select order_id, user_id, status, created_at
    from {{ ref('stg_thelook__orders') }}

),

item_totals as (

    select
        order_id,
        count(*)                                        as item_count,
        sum(case when is_returned then 1 else 0 end)    as returned_item_count,
        sum(sale_price)                                 as gross_revenue,
        sum(product_cost)                               as total_cost,
        sum(gross_margin)                               as gross_margin
    from {{ ref('int_order_items__enriched') }}
    group by order_id

)

select
    orders.order_id,
    orders.user_id,
    orders.status                                                           as order_status,
    orders.created_at                                                       as order_created_at,
    cast(orders.created_at as date)                                         as order_date,
    cast(coalesce(item_totals.item_count, 0) as {{ int_type() }})                     as item_count,
    cast(coalesce(item_totals.returned_item_count, 0) as {{ int_type() }})            as returned_item_count,
    cast(coalesce(item_totals.gross_revenue, 0) as {{ money_type() }})      as gross_revenue,
    cast(coalesce(item_totals.total_cost, 0) as {{ money_type() }})         as total_cost,
    cast(coalesce(item_totals.gross_margin, 0) as {{ money_type() }})       as gross_margin,
    coalesce(item_totals.item_count, 0) > 0
        and item_totals.returned_item_count = item_totals.item_count        as is_fully_returned
from orders
left join item_totals
    on item_totals.order_id = orders.order_id
