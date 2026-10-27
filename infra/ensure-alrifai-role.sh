#!/usr/bin/env bash
set -euo pipefail

secret_file=/etc/vps/infra/alrifai_app_password
compose_file=/opt/vps/infra/compose.yaml

if [[ ! -r "$secret_file" ]]; then
  echo "Application role password file is missing or unreadable." >&2
  exit 1
fi

app_password=$(<"$secret_file")
if [[ ! "$app_password" =~ ^[a-f0-9]{64}$ ]]; then
  echo "Application role password file has an unexpected format." >&2
  exit 1
fi

docker compose -f "$compose_file" exec -T postgres \
  psql -U vps_pg_admin -d alrifai -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'alrifai_app') THEN
    EXECUTE format(
      'CREATE ROLE alrifai_app WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD %L',
      '$app_password'
    );
  ELSE
    EXECUTE format(
      'ALTER ROLE alrifai_app WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD %L',
      '$app_password'
    );
  END IF;
END
\$\$;
ALTER DATABASE alrifai OWNER TO alrifai_app;
SQL
