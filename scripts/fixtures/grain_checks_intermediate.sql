-- Grain checks for the 11 intermediate views (run after `make duck`):
--   duckdb -readonly dev.duckdb -f scripts/fixtures/grain_checks_intermediate.sql
-- Per model: rows, distinct key values, null keys. The grain holds when
-- rows = distinct_keys and null_keys = 0 (grain_ok = true).

select model, key_column, rows, distinct_keys, null_keys,
       rows = distinct_keys and null_keys = 0 as grain_ok
from (
    select 'int_order_items__enriched' as model, 'order_item_id' as key_column,
           count(*) as rows, count(distinct order_item_id) as distinct_keys,
           count(*) - count(order_item_id) as null_keys
    from main.int_order_items__enriched
    union all
    select 'int_orders__item_rollup', 'order_id',
           count(*), count(distinct order_id), count(*) - count(order_id)
    from main.int_orders__item_rollup
    union all
    select 'int_orders__daily', 'order_date',
           count(*), count(distinct order_date), count(*) - count(order_date)
    from main.int_orders__daily
    union all
    select 'int_users__lifetime_orders', 'user_id',
           count(*), count(distinct user_id), count(*) - count(user_id)
    from main.int_users__lifetime_orders
    union all
    select 'int_users__first_order_cohort', 'user_id',
           count(*), count(distinct user_id), count(*) - count(user_id)
    from main.int_users__first_order_cohort
    union all
    select 'int_cohorts__user_months', 'user_month_key',
           count(*), count(distinct user_month_key), count(*) - count(user_month_key)
    from main.int_cohorts__user_months
    union all
    select 'int_cohorts__user_months', '(user_id, activity_month)',
           count(*), count(distinct (user_id, activity_month)),
           count(*) filter (where user_id is null or activity_month is null)
    from main.int_cohorts__user_months
    union all
    select 'int_products__sales', 'product_id',
           count(*), count(distinct product_id), count(*) - count(product_id)
    from main.int_products__sales
    union all
    select 'int_products__returns', 'product_id',
           count(*), count(distinct product_id), count(*) - count(product_id)
    from main.int_products__returns
    union all
    select 'int_inventory_items__enriched', 'inventory_item_id',
           count(*), count(distinct inventory_item_id), count(*) - count(inventory_item_id)
    from main.int_inventory_items__enriched
    union all
    select 'int_inventory__by_product_center', 'product_center_key',
           count(*), count(distinct product_center_key), count(*) - count(product_center_key)
    from main.int_inventory__by_product_center
    union all
    select 'int_inventory__by_product_center', '(product_id, distribution_center_id)',
           count(*), count(distinct (product_id, distribution_center_id)),
           count(*) filter (where product_id is null or distribution_center_id is null)
    from main.int_inventory__by_product_center
    union all
    select 'int_events__sessions', 'session_id',
           count(*), count(distinct session_id), count(*) - count(session_id)
    from main.int_events__sessions
);

-- Cross-model reconciliation: each row must be true.
select 'order items 8000 = sum(item_count)' as check_name,
       (select sum(item_count) from main.int_orders__item_rollup) = 8000 as ok
union all
select 'inventory_item_id unique in int_order_items__enriched',
       (select count(distinct inventory_item_id) = count(*) from main.int_order_items__enriched)
union all
select 'gross revenue ties: staging = daily = users = products = cohorts',
       (select sum(sale_price) from main.stg_thelook__order_items)
           = (select sum(gross_revenue) from main.int_orders__daily)
   and (select sum(gross_revenue) from main.int_orders__daily)
           = (select sum(lifetime_gross_revenue) from main.int_users__lifetime_orders)
   and (select sum(lifetime_gross_revenue) from main.int_users__lifetime_orders)
           = (select sum(gross_revenue) from main.int_products__sales)
   and (select sum(gross_revenue) from main.int_products__sales)
           = (select sum(revenue) from main.int_cohorts__user_months)
union all
select 'inventory: 10000 units = 8000 sold + 2000 open',
       (select sum(inventory_units) = 10000 and sum(sold_units) = 8000 and sum(open_units) = 2000
        from main.int_inventory__by_product_center)
union all
select 'sessions cover all 20000 events',
       (select sum(event_count) = 20000 from main.int_events__sessions)
union all
select 'return_rate within [0, 1]',
       (select bool_and(return_rate between 0 and 1) from main.int_products__returns)
union all
select 'days_to_sell null iff unsold, and >= 0',
       (select bool_and((days_to_sell is null) = (not is_sold) and coalesce(days_to_sell, 0) >= 0)
        from main.int_inventory_items__enriched)
union all
select 'cohort_month <= activity_month, both month starts',
       (select bool_and(cohort_month <= activity_month
                        and activity_month = date_trunc('month', activity_month)
                        and cohort_month = date_trunc('month', cohort_month))
        from main.int_cohorts__user_months)
union all
select 'user_month_key = md5(user_id || ''||'' || yyyymm)',
       (select bool_and(user_month_key = md5(user_id::varchar || '||'
                            || strftime(activity_month, '%Y%m')))
        from main.int_cohorts__user_months);
