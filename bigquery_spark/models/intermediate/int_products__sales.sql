-- Grain: one row per product, including products never sold (zero totals,
-- null first/last sale). A "unit sold" is one order item, whatever its status.
with products as (

    select product_id
    from {{ ref('stg_thelook__products') }}

),

sales as (

    select
        product_id,
        count(*)                    as units_sold,
        count(distinct order_id)    as orders_with_product,
        sum(sale_price)             as gross_revenue,
        sum(product_cost)           as total_cost,
        sum(gross_margin)           as gross_margin,
        min(order_item_created_at)  as first_sold_at,
        max(order_item_created_at)  as last_sold_at
    from {{ ref('int_order_items__enriched') }}
    group by product_id

)

select
    products.product_id,
    cast(coalesce(sales.units_sold, 0) as {{ int_type() }})                   as units_sold,
    cast(coalesce(sales.orders_with_product, 0) as {{ int_type() }})          as orders_with_product,
    cast(coalesce(sales.gross_revenue, 0) as {{ money_type() }})    as gross_revenue,
    cast(coalesce(sales.total_cost, 0) as {{ money_type() }})       as total_cost,
    cast(coalesce(sales.gross_margin, 0) as {{ money_type() }})     as gross_margin,
    sales.first_sold_at,
    sales.last_sold_at
from products
left join sales
    on sales.product_id = products.product_id
