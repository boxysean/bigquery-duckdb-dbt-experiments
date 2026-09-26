-- Grain: one row per product, including products never sold (return_rate null).
with products as (

    select product_id
    from {{ ref('stg_thelook__products') }}

),

item_returns as (

    select
        product_id,
        count(*)                                        as units_sold,
        sum(case when is_returned then 1 else 0 end)    as returned_units
    from {{ ref('int_order_items__enriched') }}
    group by product_id

)

select
    products.product_id,
    cast(coalesce(item_returns.units_sold, 0) as bigint)        as units_sold,
    cast(coalesce(item_returns.returned_units, 0) as bigint)    as returned_units,
    cast(item_returns.returned_units as {{ float_type() }})
        / nullif(item_returns.units_sold, 0)                    as return_rate
from products
left join item_returns
    on item_returns.product_id = products.product_id
