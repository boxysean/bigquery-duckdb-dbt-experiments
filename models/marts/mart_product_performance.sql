-- Grain: one row per product, including products never sold (zero units and
-- money, null rates and sale timestamps). Ranked by gross revenue.
with products as (

    select product_id, name, category, department, brand, cost, retail_price
    from {{ ref('stg_thelook__products') }}

),

sales as (

    select
        product_id,
        units_sold,
        gross_revenue,
        total_cost,
        gross_margin,
        first_sold_at,
        last_sold_at
    from {{ ref('int_products__sales') }}

),

returns as (

    select product_id, returned_units, return_rate
    from {{ ref('int_products__returns') }}

)

select
    products.product_id,
    products.name                                                       as product_name,
    products.category,
    products.department,
    products.brand,
    products.cost                                                       as unit_cost,
    products.retail_price,
    sales.units_sold,
    sales.gross_revenue,
    sales.total_cost,
    sales.gross_margin,
    cast(sales.gross_margin as {{ float_type() }})
        / nullif(cast(sales.gross_revenue as {{ float_type() }}), 0)    as gross_margin_rate,
    returns.returned_units,
    returns.return_rate,
    sales.first_sold_at,
    sales.last_sold_at
from products
left join sales
    on sales.product_id = products.product_id
left join returns
    on returns.product_id = products.product_id
order by sales.gross_revenue desc, products.product_id
