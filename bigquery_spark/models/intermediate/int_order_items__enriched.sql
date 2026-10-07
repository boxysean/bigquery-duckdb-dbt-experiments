-- Grain: one row per order item. Every join is on the joined table's primary
-- key and is a left join, so the row count equals stg_thelook__order_items.
with order_items as (

    select
        order_item_id,
        order_id,
        user_id,
        product_id,
        inventory_item_id,
        status,
        created_at,
        shipped_at,
        delivered_at,
        returned_at,
        sale_price
    from {{ ref('stg_thelook__order_items') }}

),

orders as (

    select order_id, status, created_at
    from {{ ref('stg_thelook__orders') }}

),

inventory_items as (

    select inventory_item_id, cost, distribution_center_id
    from {{ ref('stg_thelook__inventory_items') }}

),

products as (

    select product_id, category, department, brand
    from {{ ref('stg_thelook__products') }}

),

users as (

    select user_id, traffic_source
    from {{ ref('stg_thelook__users') }}

)

select
    order_items.order_item_id,
    order_items.order_id,
    order_items.user_id,
    order_items.product_id,
    order_items.inventory_item_id,
    inventory_items.distribution_center_id,
    order_items.status                                                      as order_item_status,
    orders.status                                                           as order_status,
    order_items.sale_price,
    inventory_items.cost                                                    as product_cost,
    cast(order_items.sale_price - inventory_items.cost as {{ money_type() }}) as gross_margin,
    order_items.status = 'Returned'                                         as is_returned,
    order_items.created_at                                                  as order_item_created_at,
    orders.created_at                                                       as order_created_at,
    cast(orders.created_at as date)                                         as order_date,
    order_items.shipped_at,
    order_items.delivered_at,
    order_items.returned_at,
    products.category                                                       as product_category,
    products.department                                                     as product_department,
    products.brand                                                          as product_brand,
    users.traffic_source                                                    as user_traffic_source
from order_items
left join orders
    on orders.order_id = order_items.order_id
left join inventory_items
    on inventory_items.inventory_item_id = order_items.inventory_item_id
left join products
    on products.product_id = order_items.product_id
left join users
    on users.user_id = order_items.user_id
