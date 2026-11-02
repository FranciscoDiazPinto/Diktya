#!/bin/sh
# Solo primera inicialización de un volumen vacío. Migraciones como propietario;
# API como netbot_app. psql escapa las variables como literales/identificadores.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -v db="$POSTGRES_DB" <<'SQL'
\getenv app_password NETBOT_APP_PASSWORD
CREATE ROLE netbot_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD :'app_password';
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE CONNECT ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"db" TO netbot_app;
GRANT USAGE ON SCHEMA public TO netbot_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO netbot_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO netbot_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO netbot_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO netbot_app;
SQL
