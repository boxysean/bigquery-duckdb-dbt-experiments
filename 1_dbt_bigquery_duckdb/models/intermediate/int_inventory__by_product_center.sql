-- Grain: one row per product x distribution center that holds at least one
-- unit of the product (ever stocked, sold or not).
with by_product_center as (

    select
        product_id,
        distribution_center_id,
        count(*)                                                        as inventory_units,
        sum(case when is_sold then 0 else 1 end)                        as open_units,
        sum(case when is_sold then 1 else 0 end)                        as sold_units,
        sum(case when is_sold then 0 else unit_cost end)                as open_inventory_value,
        sum(case when is_sold then 0 else product_retail_price end)     as open_retail_value
    from {{ ref('int_inventory_items__enriched') }}
    group by product_id, distribution_center_id

)

select
    {{ generate_surrogate_key(['product_id', 'distribution_center_id']) }}  as product_center_key,
    product_id,
    distribution_center_id,
    cast(inventory_units as {{ int_type() }})                                         as inventory_units,
    cast(open_units as {{ int_type() }})                                              as open_units,
    cast(sold_units as {{ int_type() }})                                              as sold_units,
    cast(open_inventory_value as {{ money_type() }})                        as open_inventory_value,
    cast(open_retail_value as {{ money_type() }})                           as open_retail_value
from by_product_center
