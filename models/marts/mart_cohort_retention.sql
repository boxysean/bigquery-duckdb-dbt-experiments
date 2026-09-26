-- Grain: one row per cohort month x activity month in which at least one
-- cohort member ordered. The cohort is the UTC month of the user's first order,
-- so every cohort's month-0 row holds the whole cohort.
with user_months as (

    select user_id, cohort_month, activity_month, orders, revenue
    from {{ ref('int_cohorts__user_months') }}
    where cohort_month is not null

),

cohort_months as (

    select
        cohort_month,
        activity_month,
        count(distinct user_id)     as customers,
        sum(orders)                 as orders,
        sum(revenue)                as revenue
    from user_months
    group by cohort_month, activity_month

),

cohort_sizes as (

    select cohort_month, customers as cohort_customers
    from cohort_months
    where activity_month = cohort_month

)

select
    {{ generate_surrogate_key([month_number('cohort_months.cohort_month'), month_number('cohort_months.activity_month')]) }}
                                                                    as cohort_activity_key,
    cohort_months.cohort_month,
    cohort_months.activity_month,
    cast(
        (extract(year from cohort_months.activity_month) - extract(year from cohort_months.cohort_month)) * 12
        + extract(month from cohort_months.activity_month) - extract(month from cohort_months.cohort_month)
        as bigint)                                                  as months_since_cohort,
    cast(cohort_months.customers as bigint)                         as customers,
    cast(cohort_months.orders as bigint)                            as orders,
    cast(cohort_months.revenue as {{ money_type() }})               as revenue,
    cast(cohort_months.customers as {{ float_type() }})
        / nullif(cohort_sizes.cohort_customers, 0)                  as retention_rate
from cohort_months
left join cohort_sizes
    on cohort_sizes.cohort_month = cohort_months.cohort_month
order by cohort_months.cohort_month, cohort_months.activity_month
