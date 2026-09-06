SELECT o.order_id, o.ordered_at, o.order_status, c.customer_name,
       sum(i.line_total) AS order_total, sum(i.quantity) AS item_count
FROM commerce.orders o
JOIN commerce.customers c USING (customer_id)
JOIN commerce.order_items i USING (order_id)
WHERE o.customer_id = {{ customer_id }}
GROUP BY o.order_id, o.ordered_at, o.order_status, c.customer_name
ORDER BY o.ordered_at, o.order_id
