-- The local stand-in for `bigquery-public-data.thelook_ecommerce` (SPEC section 2).
--
-- Run by scripts/load_duckdb_sources.sh against dev.duckdb; it (re)creates
-- dev.thelook_ecommerce.* from scratch every time. Never loaded into BigQuery.
--
-- * Columns, column order and types mirror the real BigQuery tables as DuckDB
--   sees them: INT64 -> BIGINT, FLOAT64 -> DOUBLE, STRING -> VARCHAR,
--   TIMESTAMP -> TIMESTAMPTZ (what DuckDB's bigquery extension returns),
--   GEOGRAPHY -> GEOMETRY. That includes the two geometry columns,
--   users.user_geom and distribution_centers.distribution_center_geom (last in
--   each table, as on BigQuery), built as WKT POINT(longitude latitude) from the
--   row's own lat/lon and cast to DuckDB's native GEOMETRY type (no extension).
--   The seam's spelling of that type is macros/polyglot/types.sql
--   geography_type(); this file cannot call it, because it is plain SQL run by
--   the duckdb CLI, not dbt, so it writes the DuckDB spelling directly.
--   scripts/check_source_schema.py proves fixture == declared == real.
-- * Deterministic. Every "random" draw is `hash(<row key>, '<salt>')`, a pure
--   function of the row, so the output does not depend on thread scheduling
--   (random() after setseed() is only reproducible single-threaded). setseed is
--   still called so that any future random() use is seeded too.
-- * Volumes are fixed: 10 / 200 / 400 / 10000 / 3000 / 8000 / 20000
--   (inventory_items raised from the spec's 6000 so no unit is sold twice).
--
-- Time window (UTC): users sign up between 2022-01-01 and 2025-07-01; orders and
-- events fall between the user's signup and 2026-01-01.

SELECT setseed(0.42);

-- uniform draw in [0, 1) keyed by (k, salt)
CREATE OR REPLACE TEMP MACRO rnd(k, salt) AS (hash(k, salt) % 1000000)::DOUBLE / 1000000.0;
-- deterministic pick from a list keyed by (k, salt)
CREATE OR REPLACE TEMP MACRO pick(lst, k, salt) AS lst[1 + (hash(k, salt) % len(lst))::BIGINT];

CREATE OR REPLACE TEMP MACRO window_start() AS 1640995200;  -- 2022-01-01 00:00:00 UTC
CREATE OR REPLACE TEMP MACRO signup_end()   AS 1751328000;  -- 2025-07-01 00:00:00 UTC
CREATE OR REPLACE TEMP MACRO window_end()   AS 1767225600;  -- 2026-01-01 00:00:00 UTC

CREATE SCHEMA IF NOT EXISTS thelook_ecommerce;

-- ---------------------------------------------------------------- distribution_centers (10)
CREATE OR REPLACE TABLE thelook_ecommerce.distribution_centers AS
WITH centers AS (
    SELECT * FROM (VALUES
        (1,  'Memphis TN',                                 35.1174, -89.9711),
        (2,  'Chicago IL',                                 41.8369, -87.6847),
        (3,  'Houston TX',                                 29.7604, -95.3698),
        (4,  'Los Angeles CA',                             34.0500, -118.2500),
        (5,  'New Orleans LA',                             29.9500, -90.0667),
        (6,  'Port Authority of New York/New Jersey NY/NJ', 40.6340, -73.7834),
        (7,  'Philadelphia PA',                            39.9500, -75.1667),
        (8,  'Mobile AL',                                  30.6944, -88.0431),
        (9,  'Charleston SC',                              32.7833, -79.9333),
        (10, 'Savannah GA',                                32.0167, -81.1167)
    ) AS t(id, name, latitude, longitude)
)
SELECT
    id::BIGINT                                                                     AS id,
    name::VARCHAR                                                                  AS name,
    latitude::DOUBLE                                                               AS latitude,
    longitude::DOUBLE                                                              AS longitude,
    ('POINT(' || longitude::VARCHAR || ' ' || latitude::VARCHAR || ')')::GEOMETRY   AS distribution_center_geom
FROM centers;

-- ---------------------------------------------------------------- products (200)
CREATE OR REPLACE TABLE thelook_ecommerce.products AS
WITH base AS (
    SELECT
        i AS id,
        pick(['Men', 'Women'], i, 'department') AS department,
        pick(['Levi''s', 'Diesel', 'Calvin Klein', 'Carhartt', 'Volcom', 'Wrangler',
              'Lucky Brand', 'True Religion', '7 For All Mankind', 'Hurley', 'Columbia',
              'Tommy Hilfiger'], i, 'brand') AS brand,
        pick(['Classic', 'Slim Fit', 'Relaxed', 'Vintage', 'Essential', 'Premium',
              'Everyday', 'Heritage'], i, 'style') AS style,
        round(12 + rnd(i, 'retail_price') * 140, 2) AS retail_price,
        0.35 + rnd(i, 'cost_ratio') * 0.25 AS cost_ratio
    FROM range(1, 201) AS t(i)
),
categorised AS (
    SELECT
        *,
        CASE department
            WHEN 'Men' THEN pick(['Jeans', 'Sweaters', 'Tops & Tees', 'Swim', 'Active', 'Shorts',
                                  'Outerwear & Coats', 'Pants', 'Accessories', 'Socks',
                                  'Suits & Sport Coats'], id, 'category')
            ELSE pick(['Jeans', 'Sweaters', 'Tops & Tees', 'Swim', 'Active', 'Shorts',
                       'Outerwear & Coats', 'Dresses', 'Skirts', 'Pants', 'Accessories',
                       'Socks'], id, 'category')
        END AS category
    FROM base
)
SELECT
    id::BIGINT                                              AS id,
    round(retail_price * cost_ratio, 2)::DOUBLE             AS cost,
    category::VARCHAR                                       AS category,
    (brand || ' ' || department || '''s ' || style || ' ' || category)::VARCHAR AS name,
    brand::VARCHAR                                          AS brand,
    retail_price::DOUBLE                                    AS retail_price,
    department::VARCHAR                                     AS department,
    upper(md5('sku-' || id::VARCHAR))::VARCHAR              AS sku,
    (1 + (id - 1) % 10)::BIGINT                             AS distribution_center_id
FROM categorised
ORDER BY id;

-- ---------------------------------------------------------------- users (400)
CREATE OR REPLACE TABLE thelook_ecommerce.users AS
WITH base AS (
    SELECT
        i AS id,
        pick(['M', 'F'], i, 'gender') AS gender,
        pick([
            {'city': 'New York',      'state': 'New York',       'postal_code': '10001', 'country': 'United States', 'lat': 40.7506, 'lon': -73.9972},
            {'city': 'Los Angeles',   'state': 'California',     'postal_code': '90012', 'country': 'United States', 'lat': 34.0614, 'lon': -118.2385},
            {'city': 'Chicago',       'state': 'Illinois',       'postal_code': '60601', 'country': 'United States', 'lat': 41.8858, 'lon': -87.6181},
            {'city': 'Houston',       'state': 'Texas',          'postal_code': '77002', 'country': 'United States', 'lat': 29.7566, 'lon': -95.3597},
            {'city': 'Austin',        'state': 'Texas',          'postal_code': '78701', 'country': 'United States', 'lat': 30.2711, 'lon': -97.7437},
            {'city': 'Seattle',       'state': 'Washington',     'postal_code': '98101', 'country': 'United States', 'lat': 47.6114, 'lon': -122.3305},
            {'city': 'Miami',         'state': 'Florida',        'postal_code': '33130', 'country': 'United States', 'lat': 25.7677, 'lon': -80.2044},
            {'city': 'Denver',        'state': 'Colorado',       'postal_code': '80202', 'country': 'United States', 'lat': 39.7525, 'lon': -104.9995},
            {'city': 'Shanghai',      'state': 'Shanghai',       'postal_code': '200000', 'country': 'China',        'lat': 31.2304, 'lon': 121.4737},
            {'city': 'Beijing',       'state': 'Beijing',        'postal_code': '100000', 'country': 'China',        'lat': 39.9042, 'lon': 116.4074},
            {'city': 'São Paulo',     'state': 'São Paulo',      'postal_code': '01000-000', 'country': 'Brasil',    'lat': -23.5505, 'lon': -46.6333},
            {'city': 'Seoul',         'state': 'Seoul',          'postal_code': '04524', 'country': 'South Korea',   'lat': 37.5665, 'lon': 126.9780},
            {'city': 'Manchester',    'state': 'England',        'postal_code': 'M1 1AE', 'country': 'United Kingdom', 'lat': 53.4808, 'lon': -2.2426},
            {'city': 'Madrid',        'state': 'Madrid',         'postal_code': '28001', 'country': 'Spain',         'lat': 40.4168, 'lon': -3.7038},
            {'city': 'Berlin',        'state': 'Berlin',         'postal_code': '10115', 'country': 'Germany',       'lat': 52.5200, 'lon': 13.4050},
            {'city': 'Paris',         'state': 'Île-de-France',  'postal_code': '75001', 'country': 'France',        'lat': 48.8566, 'lon': 2.3522}
        ], i, 'location') AS loc,
        pick(['Smith', 'Johnson', 'Williams', 'Brown', 'Jones', 'Garcia', 'Miller', 'Davis',
              'Rodriguez', 'Martinez', 'Lee', 'Wang', 'Kim', 'Silva', 'Müller', 'Martin'], i, 'last_name') AS last_name,
        floor(window_start() + rnd(i, 'signup') * (signup_end() - window_start())) AS signup_epoch
    FROM range(1, 401) AS t(i)
),
named AS (
    SELECT
        *,
        CASE gender
            WHEN 'M' THEN pick(['James', 'Michael', 'David', 'Daniel', 'Joseph', 'Kevin',
                                'Brian', 'Wei', 'Lucas', 'Min-jun'], id, 'first_name')
            ELSE pick(['Mary', 'Jennifer', 'Linda', 'Sarah', 'Jessica', 'Emily',
                       'Ashley', 'Mei', 'Ana', 'Ji-woo'], id, 'first_name')
        END AS first_name
    FROM base
),
located AS (
    SELECT
        id::BIGINT                                                                AS id,
        first_name::VARCHAR                                                       AS first_name,
        last_name::VARCHAR                                                        AS last_name,
        lower(replace(first_name || last_name, '-', '')) || id::VARCHAR || '@example.com' AS email,
        (12 + hash(id, 'age') % 59)::BIGINT                                       AS age,
        gender::VARCHAR                                                           AS gender,
        loc.state::VARCHAR                                                        AS state,
        ((100 + hash(id, 'street_no') % 9900)::VARCHAR || ' '
            || pick(['Oak', 'Maple', 'Cedar', 'Pine', 'Elm', 'Lake', 'Hill', 'Park'], id, 'street')
            || ' ' || pick(['Street', 'Avenue', 'Road', 'Lane'], id, 'street_kind'))::VARCHAR AS street_address,
        loc.postal_code::VARCHAR                                                  AS postal_code,
        loc.city::VARCHAR                                                         AS city,
        loc.country::VARCHAR                                                      AS country,
        round(loc.lat + (rnd(id, 'lat') - 0.5) * 0.1, 6)::DOUBLE                  AS latitude,
        round(loc.lon + (rnd(id, 'lon') - 0.5) * 0.1, 6)::DOUBLE                  AS longitude,
        pick(['Search', 'Organic', 'Facebook', 'Email', 'Display'], id, 'traffic_source')::VARCHAR AS traffic_source,
        to_timestamp(signup_epoch)                                                AS created_at
    FROM named
)
SELECT
    *,
    ('POINT(' || longitude::VARCHAR || ' ' || latitude::VARCHAR || ')')::GEOMETRY AS user_geom
FROM located
ORDER BY id;

-- ---------------------------------------------------------------- orders (3000)
-- num_of_item is 1..4 and is fixed so that the items total exactly 8000:
-- 500 x 1 + 800 x 2 + 900 x 3 + 800 x 4 = 8000.
CREATE OR REPLACE TABLE thelook_ecommerce.orders AS
WITH base AS (
    SELECT
        i AS order_id,
        (1 + hash(i, 'user') % 400)::BIGINT AS user_id,
        rnd(i, 'status') AS status_draw,
        row_number() OVER (ORDER BY hash(i, 'num_of_item'), i) AS size_rank
    FROM range(1, 3001) AS t(i)
),
timed AS (
    SELECT
        b.*,
        u.gender,
        -- at least an hour after signup, before the end of the window
        floor(epoch(u.created_at) + 3600
              + rnd(b.order_id, 'created') * (window_end() - epoch(u.created_at) - 3600)) AS created_epoch,
        CASE
            WHEN b.status_draw < 0.25 THEN 'Complete'
            WHEN b.status_draw < 0.55 THEN 'Shipped'
            WHEN b.status_draw < 0.75 THEN 'Processing'
            WHEN b.status_draw < 0.90 THEN 'Cancelled'
            ELSE 'Returned'
        END AS status,
        CASE
            WHEN b.size_rank <= 500  THEN 1
            WHEN b.size_rank <= 1300 THEN 2
            WHEN b.size_rank <= 2200 THEN 3
            ELSE 4
        END AS num_of_item
    FROM base AS b
    JOIN thelook_ecommerce.users AS u ON u.id = b.user_id
),
milestones AS (
    SELECT
        *,
        created_epoch + 21600 + floor(rnd(order_id, 'ship') * 3 * 86400)                AS shipped_epoch,
        created_epoch + 21600 + 3 * 86400 + floor(rnd(order_id, 'deliver') * 5 * 86400) AS delivered_epoch,
        created_epoch + 21600 + 8 * 86400 + floor(rnd(order_id, 'return') * 20 * 86400) AS returned_epoch
    FROM timed
)
SELECT
    order_id::BIGINT                                                              AS order_id,
    user_id::BIGINT                                                               AS user_id,
    status::VARCHAR                                                               AS status,
    gender::VARCHAR                                                               AS gender,
    to_timestamp(created_epoch)                                                   AS created_at,
    CASE WHEN status = 'Returned' THEN to_timestamp(returned_epoch) END          AS returned_at,
    CASE WHEN status IN ('Shipped', 'Complete', 'Returned') THEN to_timestamp(shipped_epoch) END AS shipped_at,
    CASE WHEN status IN ('Complete', 'Returned') THEN to_timestamp(delivered_epoch) END         AS delivered_at,
    num_of_item::BIGINT                                                           AS num_of_item
FROM milestones
ORDER BY order_id;

-- ---------------------------------------------------------------- order_items (8000), staged
-- One row per unit ordered; the item inherits its order's user, status and
-- milestones, and is created within a minute of the order. sale_price is the
-- product's retail price, as in the real dataset.
CREATE OR REPLACE TEMP TABLE order_items_staged AS
WITH exploded AS (
    SELECT o.*, s.seq
    FROM thelook_ecommerce.orders AS o,
         range(1, o.num_of_item + 1) AS s(seq)
)
SELECT
    row_number() OVER (ORDER BY e.order_id, e.seq)                 AS id,
    e.order_id,
    e.user_id,
    (1 + hash(e.order_id, e.seq, 'product') % 200)::BIGINT          AS product_id,
    e.status,
    e.created_at + to_seconds((hash(e.order_id, e.seq, 'lag') % 60)::BIGINT) AS created_at,
    e.shipped_at,
    e.delivered_at,
    e.returned_at
FROM exploded AS e;

-- ---------------------------------------------------------------- inventory_items (10000)
-- Every unit is sold at most once, as in the real dataset: order item i consumes
-- inventory unit i (units 1..8000, each of the ordered item's product), and
-- units 8001..10000 are open stock, 10 per product. sold_at is the sale time.
CREATE OR REPLACE TEMP TABLE order_item_units AS
SELECT
    id AS order_item_id,
    id AS inventory_item_id
FROM order_items_staged;

CREATE OR REPLACE TABLE thelook_ecommerce.inventory_items AS
WITH units AS (
    SELECT id, product_id FROM order_items_staged
    UNION ALL
    SELECT i AS id, 1 + (i - 8001) % 200 AS product_id
    FROM range(8001, 10001) AS t(i)
),
first_sale AS (
    SELECT u.inventory_item_id, min(s.created_at) AS sold_at
    FROM order_item_units AS u
    JOIN order_items_staged AS s ON s.id = u.order_item_id
    GROUP BY u.inventory_item_id
)
SELECT
    u.id::BIGINT                                                         AS id,
    u.product_id::BIGINT                                                 AS product_id,
    CASE
        WHEN f.sold_at IS NOT NULL
            THEN f.sold_at - to_seconds(floor(86400 + rnd(u.id, 'stock_age') * 120 * 86400)::BIGINT)
        ELSE to_timestamp(floor(window_start() + rnd(u.id, 'stocked') * (window_end() - window_start())))
    END                                                                  AS created_at,
    f.sold_at                                                            AS sold_at,
    p.cost::DOUBLE                                                       AS cost,
    p.category::VARCHAR                                                  AS product_category,
    p.name::VARCHAR                                                      AS product_name,
    p.brand::VARCHAR                                                     AS product_brand,
    p.retail_price::DOUBLE                                               AS product_retail_price,
    p.department::VARCHAR                                                AS product_department,
    p.sku::VARCHAR                                                       AS product_sku,
    p.distribution_center_id::BIGINT                                     AS product_distribution_center_id
FROM units AS u
JOIN thelook_ecommerce.products AS p ON p.id = u.product_id
LEFT JOIN first_sale AS f ON f.inventory_item_id = u.id
ORDER BY u.id;

-- ---------------------------------------------------------------- order_items (8000)
CREATE OR REPLACE TABLE thelook_ecommerce.order_items AS
SELECT
    s.id::BIGINT                   AS id,
    s.order_id::BIGINT             AS order_id,
    s.user_id::BIGINT              AS user_id,
    s.product_id::BIGINT           AS product_id,
    u.inventory_item_id::BIGINT    AS inventory_item_id,
    s.status::VARCHAR              AS status,
    s.created_at                   AS created_at,
    s.shipped_at                   AS shipped_at,
    s.delivered_at                 AS delivered_at,
    s.returned_at                  AS returned_at,
    p.retail_price::DOUBLE         AS sale_price
FROM order_items_staged AS s
JOIN order_item_units AS u ON u.order_item_id = s.id
JOIN thelook_ecommerce.products AS p ON p.id = s.product_id
ORDER BY s.id;

-- ---------------------------------------------------------------- events (20000)
-- Sessions of 2..8 events for registered users, cut off at exactly 20000 events
-- (the last session is truncated, so it still starts at sequence_number 1).
-- Each session: home -> department -> product... and, when it is at least 5
-- events long, cart -> purchase or cancel.
CREATE OR REPLACE TABLE thelook_ecommerce.events AS
WITH sessions AS (
    SELECT
        s AS session_no,
        (1 + hash(s, 'user') % 400)::BIGINT AS user_id,
        (2 + hash(s, 'length') % 7)::BIGINT AS planned_length,
        md5('session-' || s::VARCHAR)       AS h
    FROM range(1, 6001) AS t(s)
),
exploded AS (
    SELECT s.*, q.seq
    FROM sessions AS s, range(1, s.planned_length + 1) AS q(seq)
),
numbered AS (
    SELECT *, row_number() OVER (ORDER BY session_no, seq) AS id
    FROM exploded
),
kept AS (
    SELECT *, count(*) OVER (PARTITION BY session_no) AS session_length
    FROM numbered
    WHERE id <= 20000
),
placed AS (
    SELECT
        k.*,
        u.city, u.state, u.postal_code,
        floor(epoch(u.created_at) + 60
              + rnd(k.session_no, 'start') * (window_end() - epoch(u.created_at) - 3600)) AS start_epoch,
        pick(['Men', 'Women'], k.session_no, 'department') AS department,
        (1 + hash(k.session_no, k.seq, 'product') % 200)::BIGINT AS viewed_product_id,
        CASE
            WHEN k.seq = 1 THEN 'home'
            WHEN k.seq = 2 THEN 'department'
            WHEN k.session_length >= 5 AND k.seq = k.session_length
                THEN CASE WHEN rnd(k.session_no, 'converts') < 0.8 THEN 'purchase' ELSE 'cancel' END
            WHEN k.session_length >= 5 AND k.seq = k.session_length - 1 THEN 'cart'
            ELSE 'product'
        END AS event_type
    FROM kept AS k
    JOIN thelook_ecommerce.users AS u ON u.id = k.user_id
)
SELECT
    id::BIGINT                                                                    AS id,
    user_id::BIGINT                                                               AS user_id,
    seq::BIGINT                                                                   AS sequence_number,
    (substr(h, 1, 8) || '-' || substr(h, 9, 4) || '-' || substr(h, 13, 4) || '-'
        || substr(h, 17, 4) || '-' || substr(h, 21, 12))::VARCHAR                 AS session_id,
    to_timestamp(start_epoch + (seq - 1) * 45 + hash(session_no, seq, 'gap') % 30) AS created_at,
    ((hash(session_no, 'ip1') % 223 + 1)::VARCHAR || '.' || (hash(session_no, 'ip2') % 256)::VARCHAR || '.'
        || (hash(session_no, 'ip3') % 256)::VARCHAR || '.' || (hash(session_no, 'ip4') % 254 + 1)::VARCHAR)::VARCHAR AS ip_address,
    city::VARCHAR                                                                 AS city,
    state::VARCHAR                                                                AS state,
    postal_code::VARCHAR                                                          AS postal_code,
    pick(['Chrome', 'Firefox', 'Safari', 'IE', 'Other'], session_no, 'browser')::VARCHAR AS browser,
    -- the real events vocabulary, measured 2026-09-27 (it is NOT the users one:
    -- users.traffic_source is Search/Organic/Facebook/Email/Display). Keeping the
    -- fixture on the measured events set is what lets the accepted_values test on
    -- stg_thelook__events.traffic_source be the same strict test on both legs.
    pick(['Email', 'Adwords', 'Facebook', 'YouTube', 'Organic'], session_no, 'traffic_source')::VARCHAR AS traffic_source,
    (CASE event_type
        WHEN 'home'       THEN '/'
        WHEN 'department' THEN '/department/' || lower(department)
        WHEN 'product'    THEN '/product/' || viewed_product_id::VARCHAR
        ELSE '/' || event_type
    END)::VARCHAR                                                                 AS uri,
    event_type::VARCHAR                                                           AS event_type
FROM placed
ORDER BY id;
