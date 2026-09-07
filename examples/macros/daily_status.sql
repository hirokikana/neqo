SELECT *
FROM (VALUES
    ('2026-09-05', 1200, 80, 20),
    ('2026-09-06', 1500, 50, 35),
    ('2026-09-07', 1100, 120, 60)
) AS daily(day, success, client_error, server_error)
ORDER BY day
