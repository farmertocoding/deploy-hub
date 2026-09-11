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
	GRANT SELECT ON ALL TABLES IN SCHEMA public TO hub_probes;
	GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO hub_probes;
	DO \$\$
	DECLARE
	    r record;
	    fleet text[] := ARRAY[
	        'vault_secret', 'vault_backupunit',
	        'core_workspacemembership', 'auth_user', 'django_session',
	        'core_project', 'core_site', 'core_siteinstance',
	        'deploys_manifest', 'deploys_deployment', 'deploys_deploymentstep',
	        'core_partner', 'core_partnersite'
	    ];
	    probe text[] := ARRAY[
	        'core_target', 'core_finding',
	        'core_alertdelivery', 'core_alertstate', 'core_checkrun'
	    ];
	BEGIN
	    FOR r IN SELECT unnest(fleet) AS tablename LOOP
	        IF to_regclass('public.' || r.tablename) IS NOT NULL THEN
	            EXECUTE format('REVOKE INSERT, UPDATE, DELETE ON TABLE %I FROM hub_probes', r.tablename);
	        END IF;
	    END LOOP;
	    FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = 'public'
	        AND (tablename LIKE 'monitor_%' OR tablename = ANY(probe))
	    LOOP
	        EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE %I TO hub_probes', r.tablename);
	    END LOOP;
	END
	\$\$;
	ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO hub_probes;
	ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO hub_probes;
EOSQL
