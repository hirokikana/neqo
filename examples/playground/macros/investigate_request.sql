SELECT l.request_id, l.trace_id, l.request_timestamp, l.status, l.error_code,
       l.request_time, s.service_name, s.owner_team, c.customer_name,
       c.account_tier, o.order_id, o.order_status, p.payment_status
FROM main.access_logs l
LEFT JOIN ops.services s ON s.service_id = l.service_id
LEFT JOIN commerce.customers c ON c.customer_id = l.customer_id
LEFT JOIN commerce.orders o ON o.order_id = l.order_id
LEFT JOIN commerce.payments p ON p.order_id = o.order_id
WHERE l.request_id = {{ request_id }}
