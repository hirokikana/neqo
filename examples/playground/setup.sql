-- Synthetic, deterministic data only. Run against a new, empty DuckDB database.
CREATE SCHEMA commerce;
CREATE SCHEMA ops;
CREATE SCHEMA analytics;
CREATE SCHEMA audit;

CREATE TABLE ops.services (
    service_id INTEGER PRIMARY KEY,
    service_name VARCHAR,
    owner_team VARCHAR,
    environment VARCHAR,
    region VARCHAR,
    slo_target DECIMAL(5, 2)
);
INSERT INTO ops.services VALUES
    (1, 'gateway', 'platform', 'production', 'ap-northeast-1', 99.95),
    (2, 'checkout', 'payments', 'production', 'ap-northeast-1', 99.90),
    (3, 'catalog', 'commerce', 'production', 'us-east-1', 99.90),
    (4, 'identity', 'platform', 'staging', 'ap-northeast-1', 99.50);

CREATE TABLE commerce.customers AS
SELECT i::INTEGER AS customer_id,
       'customer-' || lpad(i::VARCHAR, 4, '0') AS customer_name,
       'customer' || i || '@example.invalid' AS email,
       CASE WHEN i % 2 = 0 THEN 'JP' ELSE 'US' END AS country_code,
       CASE WHEN i % 5 = 0 THEN 'enterprise' ELSE 'standard' END AS account_tier,
       DATE '2025-01-01' + (i % 365)::INTEGER AS created_date,
       i % 9 <> 0 AS is_active
FROM range(1, 101) AS r(i);

CREATE TABLE commerce.products AS
SELECT i::INTEGER AS product_id,
       'SKU-' || lpad(i::VARCHAR, 4, '0') AS sku,
       'Demo product ' || i AS product_name,
       CASE WHEN i % 2 = 0 THEN 'software' ELSE 'accessories' END AS category,
       (i * 125 + 500)::DECIMAL(12, 2) AS unit_price,
       'JPY' AS currency,
       ['demo', CASE WHEN i % 2 = 0 THEN 'digital' ELSE 'physical' END] AS tags
FROM range(1, 31) AS r(i);

CREATE TABLE commerce.orders AS
SELECT i::INTEGER AS order_id,
       (i % 100 + 1)::INTEGER AS customer_id,
       TIMESTAMP '2026-09-03 00:00:00' + (i % 72) * INTERVAL '1 hour' AS ordered_at,
       CASE WHEN i % 11 = 0 THEN 'failed'
            WHEN i % 5 = 0 THEN 'pending' ELSE 'completed' END AS order_status,
       'JPY' AS currency,
       CASE WHEN i % 4 = 0 THEN 'WELCOME' ELSE NULL END AS coupon_code,
       json_object('source', 'demo', 'campaign', 'autumn') AS metadata
FROM range(1, 301) AS r(i);

CREATE TABLE commerce.order_items AS
SELECT (o.order_id * 10 + n)::INTEGER AS order_item_id,
       o.order_id,
       p.product_id,
       n::INTEGER AS quantity,
       p.unit_price,
       (p.unit_price * n)::DECIMAL(12, 2) AS line_total
FROM commerce.orders o
CROSS JOIN range(1, 3) AS r(n)
JOIN commerce.products p ON p.product_id = (o.order_id + n) % 30 + 1;

CREATE TABLE commerce.payments AS
SELECT order_id AS payment_id, order_id,
       'pay-' || lpad(order_id::VARCHAR, 6, '0') AS provider_reference,
       CASE WHEN order_id % 11 = 0 THEN 'declined' ELSE 'captured' END AS payment_status,
       'card' AS payment_method,
       ordered_at + INTERVAL '2 seconds' AS processed_at
FROM commerce.orders;

CREATE TABLE access_logs AS
SELECT 'req-' || lpad(i::VARCHAR, 6, '0') AS request_id,
       'trace-' || lpad((i / 3)::INTEGER::VARCHAR, 6, '0') AS trace_id,
       DATE '2026-09-03' + (i % 3)::INTEGER AS dt,
       TIMESTAMP '2026-09-03 00:00:00' + (i % 3) * INTERVAL '1 day'
           + (i % 86400) * INTERVAL '1 second' AS request_timestamp,
       (i % 4 + 1)::INTEGER AS service_id,
       (i % 100 + 1)::INTEGER AS customer_id,
       ((i - 1) % 300 + 1)::INTEGER AS order_id,
       CASE WHEN i % 2 = 0 THEN 'POST' ELSE 'GET' END AS request_method,
       CASE WHEN i % 2 = 0 THEN '/api/checkout' ELSE '/api/products' END AS request_path,
       CASE WHEN i % 7 = 0 THEN 503 WHEN i % 13 = 0 THEN 404 ELSE 200 END AS status,
       ((i % 50) * 0.1 + 0.01)::DOUBLE AS request_time,
       (i % 8192 + 128)::BIGINT AS response_bytes,
       CASE WHEN i % 7 = 0 THEN 'upstream_timeout' ELSE NULL END AS error_code,
       CASE WHEN i % 7 = 0 THEN 'Synthetic upstream timeout' ELSE NULL END AS error_message,
       '192.0.2.' || (i % 254 + 1) AS client_ip,
       struct_pack(browser := 'demo-client', version := (i % 3 + 1)::INTEGER) AS client,
       ['synthetic', CASE WHEN i % 7 = 0 THEN 'error' ELSE 'normal' END] AS tags,
       json_object('retry_count', i % 3, 'synthetic', true) AS attributes
FROM range(1, 6001) AS r(i);

CREATE TABLE access_logs_archive AS
SELECT * REPLACE (
    dt - 30 AS dt,
    request_timestamp - INTERVAL '30 days' AS request_timestamp
)
FROM access_logs
WHERE request_id <= 'req-002000';

CREATE TABLE ops.service_metrics AS
SELECT i::INTEGER AS metric_id,
       (i % 4 + 1)::INTEGER AS service_id,
       TIMESTAMP '2026-09-05 00:00:00' + (i % 1440) * INTERVAL '1 minute' AS observed_at,
       (i % 80 + 10)::DOUBLE AS cpu_percent,
       (i % 3000 + 256)::BIGINT AS memory_mb,
       (i % 20)::INTEGER AS active_connections
FROM range(1, 501) AS r(i);

CREATE TABLE audit.deployments AS
SELECT i::INTEGER AS deployment_id,
       (i % 4 + 1)::INTEGER AS service_id,
       'v1.' || i || '.0' AS version,
       TIMESTAMP '2026-09-03 00:00:00' + i * INTERVAL '1 hour' AS deployed_at,
       'demo-bot' AS deployed_by,
       CASE WHEN i % 7 = 0 THEN 'rolled_back' ELSE 'succeeded' END AS deployment_status
FROM range(1, 21) AS r(i);

CREATE MACRO error_class(code) AS
    CASE WHEN code >= 500 THEN 'server_error'
         WHEN code >= 400 THEN 'client_error' ELSE 'success' END;

CREATE VIEW access_errors AS
SELECT l.*, s.service_name, error_class(l.status) AS status_class
FROM access_logs l JOIN ops.services s USING (service_id)
WHERE l.status >= 400;

CREATE VIEW analytics.daily_service_health AS
SELECT l.dt, s.service_name, count(*) AS request_count,
       count(*) FILTER (WHERE l.status >= 500) AS server_error_count,
       round(avg(l.request_time), 3) AS avg_request_time,
       round(quantile_cont(l.request_time, 0.95), 3) AS p95_request_time
FROM access_logs l JOIN ops.services s USING (service_id)
GROUP BY l.dt, s.service_name;

CREATE VIEW analytics.order_summary AS
SELECT o.order_id, o.ordered_at, o.order_status, c.customer_name, c.country_code,
       sum(i.line_total) AS order_total, sum(i.quantity) AS item_count
FROM commerce.orders o
JOIN commerce.customers c USING (customer_id)
JOIN commerce.order_items i USING (order_id)
GROUP BY o.order_id, o.ordered_at, o.order_status, c.customer_name, c.country_code;
