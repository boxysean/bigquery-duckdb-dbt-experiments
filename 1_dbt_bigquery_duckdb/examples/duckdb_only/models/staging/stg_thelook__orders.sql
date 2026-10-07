-- [hand-moved] Worked example (card t_ef8e0090): models/staging/stg_thelook__orders.sql
-- [hand-moved] moved to DuckDB-only SQL by hand from the macro docstrings in macros/polyglot/.
with source as (

    select * from {{ source('thelook_ecommerce', 'orders') }}

),

renamed as (

    select
        cast(order_id as bigint)                  as order_id,
        cast(user_id as bigint)                   as user_id,
        cast(status as varchar)       as status,
        cast(gender as varchar)       as gender,
        timezone('UTC', cast(created_at as timestamptz))      as created_at,
        timezone('UTC', cast(returned_at as timestamptz))     as returned_at,
        timezone('UTC', cast(shipped_at as timestamptz))      as shipped_at,
        timezone('UTC', cast(delivered_at as timestamptz))    as delivered_at,
        cast(num_of_item as bigint)               as num_of_item
    from source

)

select * from renamed
