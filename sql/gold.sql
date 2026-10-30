-- Local DuckDB equivalent in Lake.gold() binds a manifest-resolved Parquet path.
SELECT currency, COUNT(*) AS transaction_count, SUM(amount_minor) AS total_minor
FROM transactions
WHERE status = 'settled'
GROUP BY currency;

-- Athena managed profile: tombstones retained for ordering, filtered for analytics.
-- CREATE OR REPLACE VIEW fluxlake.gold_daily AS
-- SELECT currency, date(occurred_at) AS day, count(*) AS transactions,
--        sum(amount_minor) AS total_minor
-- FROM fluxlake.transactions WHERE NOT deleted AND status='settled'
-- GROUP BY currency, date(occurred_at);
