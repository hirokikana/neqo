SELECT *
FROM access_logs
WHERE dt = {{ date }} AND request_time >= {{ threshold }}
