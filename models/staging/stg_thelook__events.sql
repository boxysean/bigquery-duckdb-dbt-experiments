with source as (

    select * from {{ source('thelook_ecommerce', 'events') }}

),

renamed as (

    select
        cast(id as {{ int_type() }})                              as event_id,
        cast(user_id as {{ int_type() }})                         as user_id,
        cast(sequence_number as {{ int_type() }})                 as sequence_number,
        cast(session_id as {{ string_type() }})         as session_id,
        {{ to_utc_timestamp('created_at') }}            as created_at,
        cast(ip_address as {{ string_type() }})         as ip_address,
        cast(city as {{ string_type() }})               as city,
        cast(state as {{ string_type() }})              as state,
        cast(postal_code as {{ string_type() }})        as postal_code,
        cast(browser as {{ string_type() }})            as browser,
        cast(traffic_source as {{ string_type() }})     as traffic_source,
        cast(uri as {{ string_type() }})                as uri,
        cast(event_type as {{ string_type() }})         as event_type
    from source

)

select * from renamed
