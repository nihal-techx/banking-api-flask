-- Idempotent. Run after EVERY migration. A new table gets no access until it is listed here.
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM bank_app;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM bank_app;
GRANT USAGE ON SCHEMA public TO bank_app;

-- Users are created and read, never updated or deleted by the application.
GRANT SELECT, INSERT ON users TO bank_app;

-- Balances change. Accounts are never deleted.
GRANT SELECT, INSERT, UPDATE ON accounts TO bank_app;

-- The ledger is append-only. No UPDATE, no DELETE, no TRUNCATE, ever.
GRANT SELECT, INSERT ON transactions, ledger_entries TO bank_app;

-- Operational tables that are updated and purged.
GRANT SELECT, INSERT, UPDATE, DELETE ON idempotency_keys, outbox_events TO bank_app;

GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO bank_app;