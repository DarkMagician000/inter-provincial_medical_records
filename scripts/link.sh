#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

export PGCLIENTENCODING=UTF8 PGCONNECT_TIMEOUT=10
sites=(tayninh hcm cantho dongnai)
tables=(patient visit prescription visit_cardio visit_eye visit_blood visit_eye_diagnosis visit_blood_test)

config=$(python3 -c '
import ipaddress, tomllib
with open("deploy.toml", "rb") as source:
    config = tomllib.load(source)
if config["dbname"] != "hospital" or set(config["sites"]) != {"tayninh", "hcm", "cantho", "dongnai"}:
    raise ValueError("Expected hospital database and exactly four agreed sites")
if config["sites"]["tayninh"].get("central") is not True:
    raise ValueError("Expected tayninh as central site")
endpoints = set()
for name, site in config["sites"].items():
    address = ipaddress.ip_address(site["ip"])
    port = site["port"]
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError(f"Invalid port for {name}: {port!r}")
    if (address, port) in endpoints:
        raise ValueError(f"Duplicate database endpoint for {name}")
    endpoints.add((address, port))
    print(name, address, port, sep="\t")
')
declare -A hosts ports
while IFS=$'\t' read -r site host port; do
    hosts[$site]=$host
    ports[$site]=$port
done <<< "$config"

psql_at() {
    local site=$1
    shift
    psql -h "${hosts[$site]}" -p "${ports[$site]}" -U postgres -d hospital -v ON_ERROR_STOP=1 -X -q "$@"
}

for site in "${sites[@]}"; do
    psql_at "$site" -1 -f sql/site_views.sql
done

link_args=(-1 -f -)
for site in "${sites[@]:1}"; do
    link_args+=(-v "${site}_host=${hosts[$site]}" -v "${site}_port=${ports[$site]}")
done

{
    printf '%s\n' 'CREATE EXTENSION IF NOT EXISTS postgres_fdw;'
    for site in "${sites[@]:1}"; do
        cat <<SQL
DROP SCHEMA IF EXISTS $site CASCADE;
DROP SERVER IF EXISTS $site CASCADE;
CREATE SERVER $site FOREIGN DATA WRAPPER postgres_fdw
    OPTIONS (host :'${site}_host', port :'${site}_port', dbname 'hospital',
             fetch_size '10000', async_capable 'true');
CREATE USER MAPPING FOR postgres SERVER $site OPTIONS (user 'postgres');
CREATE SCHEMA $site;
IMPORT FOREIGN SCHEMA public FROM SERVER $site INTO $site;
SQL
    done
    for table in "${tables[@]}"; do
        cat <<SQL
CREATE OR REPLACE VIEW public.all_$table AS
    SELECT * FROM public.$table
    UNION ALL SELECT * FROM hcm.$table
    UNION ALL SELECT * FROM cantho.$table
    UNION ALL SELECT * FROM dongnai.$table;
SQL
    done
} | psql_at tayninh "${link_args[@]}"
printf '%s\n' 'Central links and eight reconstruction views ready.'
