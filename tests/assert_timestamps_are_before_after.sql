-- created <= shipped <= delivered <= returned, for orders and order items,
-- comparing every pair of lifecycle timestamps that are both non-null (a null
-- comparison is not true, so it is never reported). Also: an order item is not
-- created before its order. Returns one row per violating record.
with orders as (

    select order_id, created_at, shipped_at, delivered_at, returned_at
    from {{ ref('stg_thelook__orders') }}

),

order_items as (

    select order_item_id, order_id, created_at, shipped_at, delivered_at, returned_at
    from {{ ref('stg_thelook__order_items') }}

),

lifecycles as (

    select
        'orders' as record_type,
        order_id as record_id,
        created_at,
        shipped_at,
        delivered_at,
        returned_at
    from orders

    union all

    select
        'order_items' as record_type,
        order_item_id as record_id,
        created_at,
        shipped_at,
        delivered_at,
        returned_at
    from order_items

),

lifecycle_violations as (

    select record_type, record_id
    from lifecycles
    where created_at > shipped_at
        or created_at > delivered_at
        or created_at > returned_at
        or shipped_at > delivered_at
        or shipped_at > returned_at
        or delivered_at > returned_at

),

item_before_order as (

    select 'order_item_before_order' as record_type, order_items.order_item_id as record_id
    from order_items
    inner join orders
        on orders.order_id = order_items.order_id
    where order_items.created_at < orders.created_at

)

select record_type, record_id from lifecycle_violations
union all
select record_type, record_id from item_before_order
