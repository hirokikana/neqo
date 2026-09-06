SELECT * FROM analytics.daily_service_health
WHERE dt = {{ date }}
ORDER BY server_error_count DESC, service_name
