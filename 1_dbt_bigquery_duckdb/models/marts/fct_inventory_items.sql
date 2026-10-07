-- Grain: one row per inventory item (one physical unit), sold or open.
{{ config(**physical_layout()) }}

select
    inventory_item_id,
    product_id,
    distribution_center_id,
    unit_cost,
    product_retail_price,
    created_at,
    sold_at,
    is_sold,
    days_to_sell,
    product_category,
    product_department,
    product_brand
from {{ ref('int_inventory_items__enriched') }}
