with source as (

    select * from {{ source('thelook_ecommerce', 'users') }}

),

renamed as (

    select
        cast(id as {{ int_type() }})                              as user_id,
        cast(first_name as {{ string_type() }})         as first_name,
        cast(last_name as {{ string_type() }})          as last_name,
        cast(email as {{ string_type() }})              as email,
        cast(age as {{ int_type() }})                             as age,
        cast(gender as {{ string_type() }})             as gender,
        cast(state as {{ string_type() }})              as state,
        cast(street_address as {{ string_type() }})     as street_address,
        cast(postal_code as {{ string_type() }})        as postal_code,
        cast(city as {{ string_type() }})               as city,
        cast(country as {{ string_type() }})            as country,
        cast(latitude as {{ float_type() }})            as latitude,
        cast(longitude as {{ float_type() }})           as longitude,
        cast(traffic_source as {{ string_type() }})     as traffic_source,
        {{ to_utc_timestamp('created_at') }}            as created_at
    from source

)

select * from renamed
