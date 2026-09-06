SELECT *
FROM access_logs
WHERE dt = {{ date }} AND status >= {{ status }}
