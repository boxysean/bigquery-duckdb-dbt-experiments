-- Grain: one row per inventory item (one physical unit). The product_* columns
-- are the source's denormalised copies on inventory_items, not a join.
select
    inventory_item_id,
    product_id,
    distribution_center_id,
    product_category,
    product_department,
    product_brand,
    product_name,
    product_sku,
    cost                                                        as unit_cost,
    product_retail_price,
    created_at,
    sold_at,
    sold_at is not null                                         as is_sold,
    {{ seconds_between('created_at', 'sold_at') }} / 86400.0    as days_to_sell
from {{ ref('stg_thelook__inventory_items') }}
