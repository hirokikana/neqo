SELECT l.request_id, l.request_timestamp, s.service_name, l.request_path,
       l.status, l.error_code, l.request_time
FROM main.access_logs l
JOIN ops.services s USING (service_id)
WHERE l.dt = {{ date }} AND l.status >= {{ status }}
ORDER BY l.request_time DESC, l.request_id
LIMIT {{ limit }}
