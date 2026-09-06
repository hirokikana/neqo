SELECT *
FROM access_logs
WHERE request_id = {{ request_id }}
