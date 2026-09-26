-- Coherence assertions on the STAGING views (run after `make duck`); every
-- `violations` value must be 0.
--   duckdb dev.duckdb -f scripts/fixtures/coherence_assertions_staging.sql
select 'orphan order_items (order/user/product/inventory)' as check_name, count(*) as violations
from main.stg_thelook__order_items oi
left join main.stg_thelook__orders o on o.order_id = oi.order_id
left join main.stg_thelook__users u on u.user_id = oi.user_id
left join main.stg_thelook__products p on p.product_id = oi.product_id
left join main.stg_thelook__inventory_items ii on ii.inventory_item_id = oi.inventory_item_id
where o.order_id is null or u.user_id is null or p.product_id is null or ii.inventory_item_id is null
union all
select 'orphan orders -> users', count(*) from main.stg_thelook__orders o
left join main.stg_thelook__users u using (user_id) where u.user_id is null
union all
select 'orphan events -> users', count(*) from main.stg_thelook__events e
left join main.stg_thelook__users u using (user_id) where u.user_id is null
union all
select 'orphan inventory_items -> products / distribution_centers', count(*)
from main.stg_thelook__inventory_items ii
left join main.stg_thelook__products p using (product_id)
left join main.stg_thelook__distribution_centers d on d.distribution_center_id = ii.distribution_center_id
where p.product_id is null or d.distribution_center_id is null
union all
select 'orders.num_of_item <> count(order_items)', count(*)
from main.stg_thelook__orders o
left join (select order_id, count(*) n from main.stg_thelook__order_items group by 1) c using (order_id)
where o.num_of_item <> coalesce(c.n, 0)
union all
select 'order_items created before order', count(*)
from main.stg_thelook__order_items oi join main.stg_thelook__orders o using (order_id)
where oi.created_at < o.created_at
union all
select 'created <= shipped <= delivered <= returned broken (items)', count(*)
from main.stg_thelook__order_items
where shipped_at < created_at or delivered_at < shipped_at or returned_at < delivered_at
union all
select 'inventory created_at > sold_at', count(*)
from main.stg_thelook__inventory_items where sold_at < created_at
union all
select 'inventory distribution_center_id <> products.distribution_center_id', count(*)
from main.stg_thelook__inventory_items ii join main.stg_thelook__products p using (product_id)
where ii.distribution_center_id <> p.distribution_center_id
union all
select 'sum(num_of_item) (expect 8000)', sum(num_of_item) - 8000 from main.stg_thelook__orders;

select min(created_at) as orders_from, max(created_at) as orders_to,
       (select min(created_at) from main.stg_thelook__events) as events_from,
       (select max(created_at) from main.stg_thelook__events) as events_to
from main.stg_thelook__orders;
