with source as (

    select * from {{ source('thelook_ecommerce', 'order_items') }}

),

renamed as (

    select
        cast(id as {{ int_type() }})                        as order_item_id,
        cast(order_id as {{ int_type() }})                  as order_id,
        cast(user_id as {{ int_type() }})                   as user_id,
        cast(product_id as {{ int_type() }})                as product_id,
        cast(inventory_item_id as {{ int_type() }})         as inventory_item_id,
        cast(status as {{ string_type() }})       as status,
        {{ to_utc_timestamp('created_at') }}      as created_at,
        {{ to_utc_timestamp('shipped_at') }}      as shipped_at,
        {{ to_utc_timestamp('delivered_at') }}    as delivered_at,
        {{ to_utc_timestamp('returned_at') }}     as returned_at,
        cast(sale_price as {{ money_type() }})    as sale_price
    from source

)

select * from renamed
