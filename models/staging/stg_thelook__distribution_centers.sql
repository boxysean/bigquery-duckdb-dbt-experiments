with source as (

    select * from {{ source('thelook_ecommerce', 'distribution_centers') }}

),

renamed as (

    select
        cast(id as {{ int_type() }})                      as distribution_center_id,
        cast(name as {{ string_type() }})       as name,
        cast(latitude as {{ float_type() }})    as latitude,
        cast(longitude as {{ float_type() }})   as longitude
    from source

)

select * from renamed
