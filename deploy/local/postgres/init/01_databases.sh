#!/usr/bin/env bash
# Create the local databases and their owners on the first start of an empty data volume.
# Postgres runs files in /docker-entrypoint-initdb.d only when the volume is empty, so this runs once per volume.
#   hapi       owned by hapi; HAPI FHIR creates its own tables
#   warehouse  owned by warehouse; dbt builds the analytics models here
#   grafana    owned by grafana; Grafana keeps its users, dashboards and settings here
# grafana_reader may only read the warehouse; Grafana's dashboards query through it.
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username postgres --dbname postgres \
  -v hapi_password="$LOCAL_HAPI_DB_PASSWORD" \
  -v warehouse_password="$LOCAL_WAREHOUSE_DB_PASSWORD" \
  -v grafana_password="$LOCAL_GRAFANA_DB_PASSWORD" \
  -v reader_password="$LOCAL_GRAFANA_READER_PASSWORD" <<'SQL'
CREATE ROLE hapi LOGIN PASSWORD :'hapi_password';
CREATE ROLE warehouse LOGIN PASSWORD :'warehouse_password';
CREATE ROLE grafana LOGIN PASSWORD :'grafana_password';
CREATE ROLE grafana_reader LOGIN PASSWORD :'reader_password';
CREATE DATABASE hapi OWNER hapi;
CREATE DATABASE warehouse OWNER warehouse;
CREATE DATABASE grafana OWNER grafana;
REVOKE ALL ON DATABASE hapi, warehouse, grafana FROM PUBLIC;
GRANT CONNECT ON DATABASE warehouse TO grafana_reader;
SQL

# Tables dbt creates later are readable by grafana_reader without a grant per table.
psql -v ON_ERROR_STOP=1 --username postgres --dbname warehouse <<'SQL'
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO grafana_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE warehouse GRANT USAGE ON SCHEMAS TO grafana_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE warehouse IN SCHEMA public GRANT SELECT ON TABLES TO grafana_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE warehouse GRANT SELECT ON TABLES TO grafana_reader;
SQL
