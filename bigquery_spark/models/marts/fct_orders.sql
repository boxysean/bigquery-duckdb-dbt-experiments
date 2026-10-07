-- Grain: one row per order. The order rollup plus the customer's location and
-- acquisition channel from dim_users (a left join on its primary key).
with orders as (

    select
        order_id,
        user_id,
        order_status,
        order_created_at,
        order_date,
        item_count,
        returned_item_count,
        gross_revenue,
        total_cost,
        gross_margin,
        is_fully_returned
    from {{ ref('int_orders__item_rollup') }}

),

users as (

    select user_id, country, state, traffic_source
    from {{ ref('dim_users') }}

)

select
    orders.order_id,
    orders.user_id,
    orders.order_status,
    orders.order_created_at,
    orders.order_date,
    {{ month_start('orders.order_created_at') }}    as order_month,
    orders.item_count,
    orders.returned_item_count,
    orders.gross_revenue,
    orders.total_cost,
    orders.gross_margin,
    orders.is_fully_returned,
    users.country                                   as user_country,
    users.state                                     as user_state,
    users.traffic_source                            as user_traffic_source
from orders
left join users
    on users.user_id = orders.user_id
