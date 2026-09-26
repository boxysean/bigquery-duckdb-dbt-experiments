with source as (

    select * from {{ source('thelook_ecommerce', 'products') }}

),

renamed as (

    select
        cast(id as bigint)                          as product_id,
        cast(cost as {{ money_type() }})            as cost,
        cast(category as {{ string_type() }})       as category,
        cast(name as {{ string_type() }})           as name,
        cast(brand as {{ string_type() }})          as brand,
        cast(retail_price as {{ money_type() }})    as retail_price,
        cast(department as {{ string_type() }})     as department,
        cast(sku as {{ string_type() }})            as sku,
        cast(distribution_center_id as bigint)      as distribution_center_id
    from source

)

select * from renamed
