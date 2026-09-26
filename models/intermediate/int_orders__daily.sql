-- Grain: one row per UTC calendar date on which at least one order was placed.
-- Dates with no orders are absent (there is no date spine).
select
    order_date,
    cast(count(*) as bigint)                                as order_count,
    cast(sum(item_count) as bigint)                         as order_item_count,
    cast(count(distinct user_id) as bigint)                 as customer_count,
    cast(sum(gross_revenue) as {{ money_type() }})          as gross_revenue,
    cast(sum(total_cost) as {{ money_type() }})             as total_cost,
    cast(sum(gross_margin) as {{ money_type() }})           as gross_margin,
    cast(sum(returned_item_count) as bigint)                as returned_item_count
from {{ ref('int_orders__item_rollup') }}
group by order_date
