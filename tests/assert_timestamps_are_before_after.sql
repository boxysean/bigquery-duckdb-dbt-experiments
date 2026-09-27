-- created <= shipped <= delivered <= returned, comparing every pair of lifecycle
-- timestamps that are both non-null (a null comparison is not true, so it is
-- never reported). Returns one row per violating record.
--
-- Narrowed 2026-09-27 after measuring the real dataset (see NOTES.md > "Measured
-- against the real dataset"). The pairs tested here hold on both sources:
--
--   * orders: all six pairs, 0 violations over the real 124,952 orders.
--   * order_items: shipped_at <= delivered_at <= returned_at, 0 violations over
--     the real 181,313 items.
--
-- The comparisons that involve order_items.created_at are NOT here, because the
-- real dataset breaks them: its order_items.created_at is jittered around the
-- order's timestamp rather than following it (35,535 of 181,313 items are
-- "created" after the unit shipped, and 102,260 of them are created before their
-- own order). Those live in assert_order_item_created_at_is_plausible.sql, which
-- is `severity: warn` so the fact is reported on every run without failing a
-- build on data that has always been that way.
with orders as (

    select order_id, created_at, shipped_at, delivered_at, returned_at
    from {{ ref('stg_thelook__orders') }}

),

order_items as (

    select order_item_id, created_at, shipped_at, delivered_at, returned_at
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

)

select record_type, record_id
from lifecycles
where shipped_at > delivered_at
    or shipped_at > returned_at
    or delivered_at > returned_at
    -- orders.created_at does follow the lifecycle in the real dataset; the item
    -- timestamp does not, so it is only compared for orders here.
    or (
        record_type = 'orders'
        and (
            created_at > shipped_at
            or created_at > delivered_at
            or created_at > returned_at
        )
    )
