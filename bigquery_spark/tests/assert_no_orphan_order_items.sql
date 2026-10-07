-- Every order item has an order, a user and a product, and the item's user_id
-- is its order's user_id (a relationships test cannot express that agreement).
-- Checked on staging, the layer closest to the source. Returns violating rows.
with order_items as (

    select order_item_id, order_id, user_id, product_id
    from {{ ref('stg_thelook__order_items') }}

),

orders as (

    select order_id, user_id
    from {{ ref('stg_thelook__orders') }}

),

users as (

    select user_id
    from {{ ref('stg_thelook__users') }}

),

products as (

    select product_id
    from {{ ref('stg_thelook__products') }}

)

select
    order_items.order_item_id,
    order_items.order_id,
    order_items.user_id,
    order_items.product_id,
    orders.order_id is null                 as missing_order,
    users.user_id is null                   as missing_user,
    products.product_id is null             as missing_product,
    orders.user_id                          as order_user_id
from order_items
left join orders
    on orders.order_id = order_items.order_id
left join users
    on users.user_id = order_items.user_id
left join products
    on products.product_id = order_items.product_id
where orders.order_id is null
    or users.user_id is null
    or products.product_id is null
    or orders.user_id <> order_items.user_id
