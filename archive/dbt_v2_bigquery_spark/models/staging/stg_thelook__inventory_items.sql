-- Keeps the source's denormalised product_* columns; staging joins nothing.
with source as (

    select * from {{ source('thelook_ecommerce', 'inventory_items') }}

),

renamed as (

    select
        cast(id as {{ int_type() }})                                  as inventory_item_id,
        cast(product_id as {{ int_type() }})                          as product_id,
        {{ to_utc_timestamp('created_at') }}                as created_at,
        {{ to_utc_timestamp('sold_at') }}                   as sold_at,
        cast(cost as {{ money_type() }})                    as cost,
        cast(product_category as {{ string_type() }})       as product_category,
        cast(product_name as {{ string_type() }})           as product_name,
        cast(product_brand as {{ string_type() }})          as product_brand,
        cast(product_retail_price as {{ money_type() }})    as product_retail_price,
        cast(product_department as {{ string_type() }})     as product_department,
        cast(product_sku as {{ string_type() }})            as product_sku,
        cast(product_distribution_center_id as {{ int_type() }})      as distribution_center_id
    from source

)

select * from renamed
