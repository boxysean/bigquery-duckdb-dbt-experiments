-- Grain: one row per distribution center, including a center that holds no
-- stock (zero unit counts and value).
with centers as (

    select distribution_center_id, name, latitude, longitude
    from {{ ref('stg_thelook__distribution_centers') }}

),

stock as (

    select
        distribution_center_id,
        sum(inventory_units)        as inventory_units,
        sum(open_units)             as open_units,
        sum(sold_units)             as sold_units,
        sum(open_inventory_value)   as open_inventory_value
    from {{ ref('int_inventory__by_product_center') }}
    group by distribution_center_id

)

select
    centers.distribution_center_id,
    centers.name,
    centers.latitude,
    centers.longitude,
    cast(coalesce(stock.inventory_units, 0) as bigint)                  as inventory_units,
    cast(coalesce(stock.open_units, 0) as bigint)                       as open_units,
    cast(coalesce(stock.sold_units, 0) as bigint)                       as sold_units,
    cast(coalesce(stock.open_inventory_value, 0) as {{ money_type() }}) as open_inventory_value
from centers
left join stock
    on stock.distribution_center_id = centers.distribution_center_id
