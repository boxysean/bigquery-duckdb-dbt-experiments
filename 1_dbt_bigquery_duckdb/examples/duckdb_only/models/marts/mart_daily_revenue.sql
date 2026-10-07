-- [hand-moved] Worked example (card t_ef8e0090): models/marts/mart_daily_revenue.sql
-- [hand-moved] moved to DuckDB-only SQL by hand from the macro docstrings in macros/polyglot/.
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
    cast(round(gross_revenue / nullif(order_count, 0), 2) as decimal(18,2))
                                                                        as average_order_value,
    returned_item_count
from {{ ref('int_orders__daily') }}
order by revenue_date
