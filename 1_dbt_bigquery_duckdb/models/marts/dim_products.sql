-- Grain: one row per product, including products never sold (zero units and
-- money, null return_rate).
with products as (

    select
        product_id,
        name,
        sku,
        category,
        department,
        brand,
        distribution_center_id,
        cost,
        retail_price
    from {{ ref('stg_thelook__products') }}

),

centers as (

    select distribution_center_id, name
    from {{ ref('stg_thelook__distribution_centers') }}

),

sales as (

    select product_id, units_sold, gross_revenue, gross_margin
    from {{ ref('int_products__sales') }}

),

returns as (

    select product_id, returned_units, return_rate
    from {{ ref('int_products__returns') }}

)

select
    products.product_id,
    products.name                       as product_name,
    products.sku,
    products.category,
    products.department,
    products.brand,
    products.distribution_center_id,
    centers.name                        as distribution_center_name,
    products.cost                       as unit_cost,
    products.retail_price,
    sales.units_sold,
    sales.gross_revenue,
    sales.gross_margin,
    returns.returned_units,
    returns.return_rate
from products
left join centers
    on centers.distribution_center_id = products.distribution_center_id
left join sales
    on sales.product_id = products.product_id
left join returns
    on returns.product_id = products.product_id
