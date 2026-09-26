-- Grain: one row per order item. The enriched item plus product name and list
-- price from dim_products and the customer's location from dim_users (left
-- joins on their primary keys, so the row count equals the order items).
with order_items as (

    select
        order_item_id,
        order_id,
        user_id,
        product_id,
        inventory_item_id,
        distribution_center_id,
        order_item_status,
        order_status,
        sale_price,
        product_cost,
        gross_margin,
        is_returned,
        order_item_created_at,
        order_date,
        product_category,
        product_department,
        product_brand
    from {{ ref('int_order_items__enriched') }}

),

products as (

    select product_id, product_name, retail_price
    from {{ ref('dim_products') }}

),

users as (

    select user_id, country, state
    from {{ ref('dim_users') }}

)

select
    order_items.order_item_id,
    order_items.order_id,
    order_items.user_id,
    order_items.product_id,
    order_items.inventory_item_id,
    order_items.distribution_center_id,
    order_items.order_item_status,
    order_items.order_status,
    order_items.sale_price,
    order_items.product_cost,
    order_items.gross_margin,
    order_items.is_returned,
    order_items.order_item_created_at,
    order_items.order_date,
    products.product_name,
    order_items.product_category,
    order_items.product_department,
    order_items.product_brand,
    products.retail_price               as product_retail_price,
    users.country                       as user_country,
    users.state                         as user_state
from order_items
left join products
    on products.product_id = order_items.product_id
left join users
    on users.user_id = order_items.user_id
