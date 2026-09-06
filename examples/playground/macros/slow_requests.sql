SELECT l.request_id, s.service_name, l.request_path, l.status,
       l.request_time, l.client, l.tags, l.attributes
FROM main.access_logs l
JOIN ops.services s USING (service_id)
WHERE l.dt = {{ date }} AND l.request_time >= {{ threshold }}
ORDER BY l.request_time DESC, l.request_id
LIMIT {{ limit }}
