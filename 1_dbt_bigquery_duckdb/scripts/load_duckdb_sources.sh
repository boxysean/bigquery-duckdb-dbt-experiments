#!/usr/bin/env bash
#
# Load the local thelook_ecommerce fixture into dev.duckdb (SPEC section 2).
#
#   scripts/load_duckdb_sources.sh          # or: make fixtures
#
# (Re)creates dev.thelook_ecommerce.* from scripts/fixtures/thelook_ecommerce.sql
# on every run, prints every table's row count, then checks referential integrity
# and the fixture's coherence rules. Any orphan or broken rule -> exit 1.
#
# This is the DuckDB target's stand-in for bigquery-public-data.thelook_ecommerce.
# It is deliberately not `dbt seed`: the BigQuery target must never receive it.
#
# Overrides: DUCKDB_BIN (default: duckdb on PATH), DUCKDB_DB (default: dev.duckdb
# in the repo root), FIXTURE_SQL (default: scripts/fixtures/thelook_ecommerce.sql;
# pointing it at a deliberately broken copy is how the failing path is shown).
#
set -euo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"

DUCKDB_BIN=${DUCKDB_BIN:-duckdb}
DUCKDB_DB=${DUCKDB_DB:-$repo_root/dev.duckdb}
fixture_sql=${FIXTURE_SQL:-$repo_root/scripts/fixtures/thelook_ecommerce.sql}

if ! command -v "$DUCKDB_BIN" >/dev/null 2>&1; then
    printf 'FAIL  DuckDB CLI not found (%s). Run `make setup` or set DUCKDB_BIN.\n' "$DUCKDB_BIN" >&2
    exit 1
fi

query() { "$DUCKDB_BIN" -bail -noheader -list -separator '|' "$DUCKDB_DB" -c "$1"; }

printf 'Loading %s into %s (schema thelook_ecommerce)\n' "${fixture_sql#"$repo_root"/}" "${DUCKDB_DB#"$repo_root"/}"
"$DUCKDB_BIN" -bail "$DUCKDB_DB" < "$fixture_sql" > /dev/null

printf '\nRow counts:\n'
query "
select 'distribution_centers', count(*) from thelook_ecommerce.distribution_centers union all
select 'products',             count(*) from thelook_ecommerce.products             union all
select 'users',                count(*) from thelook_ecommerce.users                union all
select 'inventory_items',      count(*) from thelook_ecommerce.inventory_items      union all
select 'orders',               count(*) from thelook_ecommerce.orders               union all
select 'order_items',          count(*) from thelook_ecommerce.order_items          union all
select 'events',               count(*) from thelook_ecommerce.events
" | while IFS='|' read -r name n; do printf '  %-22s %6s\n' "$name" "$n"; done

# Every check is a count of violating rows; 0 means the rule holds.
checks="
select 'orphan order_items.order_id -> orders', count(*)
  from thelook_ecommerce.order_items oi left join thelook_ecommerce.orders o on o.order_id = oi.order_id
  where o.order_id is null
union all select 'orphan order_items.user_id -> users', count(*)
  from thelook_ecommerce.order_items oi left join thelook_ecommerce.users u on u.id = oi.user_id
  where u.id is null
union all select 'orphan order_items.product_id -> products', count(*)
  from thelook_ecommerce.order_items oi left join thelook_ecommerce.products p on p.id = oi.product_id
  where p.id is null
union all select 'orphan order_items.inventory_item_id -> inventory_items', count(*)
  from thelook_ecommerce.order_items oi left join thelook_ecommerce.inventory_items ii on ii.id = oi.inventory_item_id
  where ii.id is null
union all select 'orphan orders.user_id -> users', count(*)
  from thelook_ecommerce.orders o left join thelook_ecommerce.users u on u.id = o.user_id
  where u.id is null
union all select 'orphan inventory_items.product_id -> products', count(*)
  from thelook_ecommerce.inventory_items ii left join thelook_ecommerce.products p on p.id = ii.product_id
  where p.id is null
union all select 'orphan products.distribution_center_id -> distribution_centers', count(*)
  from thelook_ecommerce.products p left join thelook_ecommerce.distribution_centers d on d.id = p.distribution_center_id
  where d.id is null
union all select 'orphan events.user_id -> users', count(*)
  from thelook_ecommerce.events e left join thelook_ecommerce.users u on u.id = e.user_id
  where u.id is null
union all select 'order_items.user_id <> orders.user_id', count(*)
  from thelook_ecommerce.order_items oi join thelook_ecommerce.orders o using (order_id)
  where oi.user_id <> o.user_id
union all select 'orders.num_of_item <> count(order_items)', count(*)
  from thelook_ecommerce.orders o
  left join (select order_id, count(*) n from thelook_ecommerce.order_items group by 1) c using (order_id)
  where o.num_of_item <> coalesce(c.n, 0)
union all select 'order_items.product_id <> inventory_items.product_id', count(*)
  from thelook_ecommerce.order_items oi join thelook_ecommerce.inventory_items ii on ii.id = oi.inventory_item_id
  where oi.product_id <> ii.product_id
union all select 'orders.created_at > order_items.created_at', count(*)
  from thelook_ecommerce.order_items oi join thelook_ecommerce.orders o using (order_id)
  where o.created_at > oi.created_at
union all select 'created > shipped > delivered > returned (orders)', count(*)
  from thelook_ecommerce.orders
  where created_at > shipped_at or shipped_at > delivered_at or delivered_at > returned_at
union all select 'created > shipped > delivered > returned (order_items)', count(*)
  from thelook_ecommerce.order_items
  where created_at > shipped_at or shipped_at > delivered_at or delivered_at > returned_at
union all select 'status/returned_at mismatch (Returned <=> returned_at not null)', count(*)
  from (select status, returned_at from thelook_ecommerce.orders
        union all select status, returned_at from thelook_ecommerce.order_items)
  where (status = 'Returned') <> (returned_at is not null)
union all select 'inventory_items: sold_at set <> unit referenced by an order item', count(*)
  from thelook_ecommerce.inventory_items ii
  where (ii.sold_at is not null)
     <> exists (select 1 from thelook_ecommerce.order_items oi where oi.inventory_item_id = ii.id)
union all select 'inventory units referenced by more than one order item', count(*)
  from (select inventory_item_id from thelook_ecommerce.order_items group by 1 having count(*) > 1)
union all select 'order_items.inventory_item_id is null', count(*)
  from thelook_ecommerce.order_items where inventory_item_id is null
union all select 'inventory_items.created_at > sold_at', count(*)
  from thelook_ecommerce.inventory_items where created_at > sold_at
union all select 'users.created_at >= first order', count(*)
  from thelook_ecommerce.users u
  join (select user_id, min(created_at) first_order_at from thelook_ecommerce.orders group by 1) f
    on f.user_id = u.id
  where u.created_at >= f.first_order_at
union all select 'order_items.sale_price <= 0', count(*)
  from thelook_ecommerce.order_items where sale_price <= 0
union all select 'products.retail_price < cost', count(*)
  from thelook_ecommerce.products where retail_price < cost
union all select 'sessions not starting at sequence_number 1', count(*)
  from (select session_id from thelook_ecommerce.events group by 1 having min(sequence_number) <> 1)
union all select 'events before the user signed up', count(*)
  from thelook_ecommerce.events e join thelook_ecommerce.users u on u.id = e.user_id
  where e.created_at < u.created_at
"

printf '\nIntegrity and coherence checks (violating rows):\n'
results=$(query "$checks")
failed=0
while IFS='|' read -r name n; do
    if [ "$n" = "0" ]; then
        printf '  ok    %-66s %s\n' "$name" "$n"
    else
        printf '  FAIL  %-66s %s\n' "$name" "$n"
        failed=1
    fi
done <<< "$results"

if [ "$failed" -ne 0 ]; then
    printf '\nFixture is NOT coherent; see FAIL lines above.\n' >&2
    exit 1
fi
printf '\nFixture loaded and coherent.\n'
