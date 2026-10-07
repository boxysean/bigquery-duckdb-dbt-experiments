-- orders.num_of_item equals the number of order items the order really has,
-- and fct_orders.item_count (which is counted, not copied) agrees with both.
-- Returns violating orders.
with orders as (

    select order_id, num_of_item
    from {{ ref('stg_thelook__orders') }}

),

item_counts as (

    select order_id, count(*) as order_item_count
    from {{ ref('stg_thelook__order_items') }}
    group by order_id

),

fct as (

    select order_id, item_count
    from {{ ref('fct_orders') }}

)

select
    orders.order_id,
    orders.num_of_item,
    coalesce(item_counts.order_item_count, 0)   as order_item_count,
    fct.item_count                              as fct_item_count
from orders
left join item_counts
    on item_counts.order_id = orders.order_id
left join fct
    on fct.order_id = orders.order_id
where orders.num_of_item is null
    or orders.num_of_item <> coalesce(item_counts.order_item_count, 0)
    or fct.item_count is null
    or fct.item_count <> coalesce(item_counts.order_item_count, 0)
