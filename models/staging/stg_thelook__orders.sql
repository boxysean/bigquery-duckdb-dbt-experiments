with source as (

    select * from {{ source('thelook_ecommerce', 'orders') }}

),

renamed as (

    select
        cast(order_id as {{ int_type() }})                  as order_id,
        cast(user_id as {{ int_type() }})                   as user_id,
        cast(status as {{ string_type() }})       as status,
        cast(gender as {{ string_type() }})       as gender,
        {{ to_utc_timestamp('created_at') }}      as created_at,
        {{ to_utc_timestamp('returned_at') }}     as returned_at,
        {{ to_utc_timestamp('shipped_at') }}      as shipped_at,
        {{ to_utc_timestamp('delivered_at') }}    as delivered_at,
        cast(num_of_item as {{ int_type() }})               as num_of_item
    from source

)

select * from renamed
