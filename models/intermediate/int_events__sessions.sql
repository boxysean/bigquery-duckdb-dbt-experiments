-- Grain: one row per session (events.session_id). traffic_source and browser
-- are the session's first event's (lowest sequence_number, ties broken by
-- event_id); user_id is the session's max non-null user_id.
with events as (

    select
        event_id,
        session_id,
        user_id,
        sequence_number,
        created_at,
        browser,
        traffic_source,
        event_type,
        row_number() over (
            partition by session_id
            order by sequence_number, event_id
        ) as event_rank
    from {{ ref('stg_thelook__events') }}

),

session_totals as (

    select
        session_id,
        max(user_id)                                                    as user_id,
        min(created_at)                                                 as first_event_at,
        max(created_at)                                                 as last_event_at,
        count(*)                                                        as event_count,
        max(sequence_number)                                            as max_sequence_number,
        max(case when event_type = 'purchase' then 1 else 0 end) = 1    as has_purchase
    from events
    group by session_id

),

first_events as (

    select session_id, traffic_source, browser
    from events
    where event_rank = 1

)

select
    session_totals.session_id,
    session_totals.user_id,
    session_totals.first_event_at,
    session_totals.last_event_at,
    {{ seconds_between('session_totals.first_event_at', 'session_totals.last_event_at') }}
                                                        as session_seconds,
    cast(session_totals.event_count as bigint)          as event_count,
    cast(session_totals.max_sequence_number as bigint)  as max_sequence_number,
    first_events.traffic_source,
    first_events.browser,
    session_totals.has_purchase
from session_totals
left join first_events
    on first_events.session_id = session_totals.session_id
