#!/bin/sh
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
	DO \$\$
	BEGIN
	    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'hub_probes') THEN
	        CREATE ROLE hub_probes LOGIN PASSWORD '$POSTGRES_PASSWORD_PROBES';
	    END IF;
	END
	\$\$;
	GRANT CONNECT ON DATABASE $POSTGRES_DB TO hub_probes;
	GRANT USAGE ON SCHEMA public TO hub_probes;
	GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO hub_probes;
	GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO hub_probes;
	REVOKE ALL ON TABLE vault_secret FROM hub_probes;
	REVOKE ALL ON TABLE vault_backupunit FROM hub_probes;
	REVOKE INSERT, UPDATE, DELETE ON TABLE core_workspacemembership FROM hub_probes;
	REVOKE INSERT, UPDATE, DELETE ON TABLE auth_user FROM hub_probes;
	REVOKE ALL ON TABLE django_session FROM hub_probes;
	ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO hub_probes;
	ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO hub_probes;
EOSQL
