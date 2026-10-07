-- Grain: one row per UTC calendar date on which at least one order was placed
-- (no date spine: days without orders are absent, not zero rows).
select
    order_date                                                          as revenue_date,
    order_count,
    order_item_count,
    customer_count,
    gross_revenue,
    total_cost,
    gross_margin,
    cast(round(gross_revenue / nullif(order_count, 0), 2) as {{ money_type() }})
                                                                        as average_order_value,
    returned_item_count
from {{ ref('int_orders__daily') }}
order by revenue_date
