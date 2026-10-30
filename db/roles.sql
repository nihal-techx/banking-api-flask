-- Creates the application's runtime role. Run once per database cluster, as an administrator:
--   psql -v ON_ERROR_STOP=1 -v app_password=SECRET -f db/roles.sql
-- Migrations keep running as the owner role. The application never connects as the owner.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'bank_app') THEN
        CREATE ROLE bank_app LOGIN;
    END IF;
END
$$;
ALTER ROLE bank_app WITH LOGIN PASSWORD :'app_password';
GRANT CONNECT ON DATABASE :"DBNAME" TO bank_app;
