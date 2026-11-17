#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

export PGCLIENTENCODING=UTF8 PGCONNECT_TIMEOUT=10
sites=(tayninh hcm cantho dongnai)
tables=(hospital drug patient visit prescription visit_cardio visit_eye visit_blood visit_eye_diagnosis visit_blood_test)

config=$(python3 -c '
import ipaddress, tomllib
with open("deploy.toml", "rb") as source:
    config = tomllib.load(source)
expected = {"tayninh": 1, "hcm": 2, "cantho": 3, "dongnai": 4}
if config["dbname"] != "hospital" or set(config["sites"]) != set(expected):
    raise ValueError("Expected hospital database and exactly four agreed sites")
endpoints = set()
for name, site_no in {"ref": 0, **expected}.items():
    site = config["ref"] if name == "ref" else config["sites"][name]
    address = ipaddress.ip_address(site["ip"])
    port = site["port"]
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError(f"Invalid port for {name}: {port!r}")
    if name != "ref" and (type(site["site_no"]) is not int or site["site_no"] != site_no):
        raise ValueError(f"Invalid site_no for {name}")
    endpoint = (address, port)
    if endpoint in endpoints:
        raise ValueError(f"Duplicate database endpoint for {name}")
    endpoints.add(endpoint)
    print(name, address, port, site_no, sep="\t")
')
declare -A hosts ports site_numbers
while IFS=$'\t' read -r site host port site_no; do
    hosts[$site]=$host
    ports[$site]=$port
    site_numbers[$site]=$site_no
done <<< "$config"

psql_at() {
    local site=$1
    shift
    psql -h "${hosts[$site]}" -p "${ports[$site]}" -U postgres -d hospital -v ON_ERROR_STOP=1 -X -q "$@"
}

for table in "${tables[@]}"; do
    if [[ ! -r "data/lab/$table.csv" || ! -s "data/lab/$table.csv" ]]; then
        printf 'Missing, unreadable or empty data/lab/%s.csv; run make data on A.\n' "$table" >&2
        exit 1
    fi
done
for site in ref "${sites[@]}"; do
    psql_at "$site" -c 'SELECT 1' >/dev/null
done

printf '%s\n' 'Reloading reference database and site fragments; existing project data will be replaced.'
reset='DROP SCHEMA public CASCADE; CREATE SCHEMA public;'
reference_args=(-1 -c "$reset" -f sql/schema_central.sql)
for table in "${tables[@]}"; do
    reference_args+=(-c "\copy $table FROM 'data/lab/$table.csv' (FORMAT csv, HEADER)")
done
psql_at ref "${reference_args[@]}" -c 'ANALYZE;'

for site in "${sites[@]}"; do
    printf 'Loading %s (%s:%s)\n' "$site" "${hosts[$site]}" "${ports[$site]}"
    psql_at "$site" -1 -c "$reset" -f sql/schema_central.sql
    patients="SELECT patient_id FROM patient WHERE home_province = '$site'"
    visits="SELECT visit_id FROM visit WHERE patient_id IN ($patients)"
    for table in "${tables[@]}"; do
        query="SELECT * FROM $table"
        case "$table" in
            hospital|drug) ;;
            patient) query+=" WHERE home_province = '$site'" ;;
            visit) query+=" WHERE patient_id IN ($patients)" ;;
            visit_eye_diagnosis) query+=" WHERE visit_id IN (SELECT visit_id FROM visit_eye WHERE visit_id IN ($visits))" ;;
            visit_blood_test) query+=" WHERE visit_id IN (SELECT visit_id FROM visit_blood WHERE visit_id IN ($visits))" ;;
            *) query+=" WHERE visit_id IN ($visits)" ;;
        esac
        printf '  %s\n' "$table"
        psql_at ref -c "\copy ($query) TO STDOUT (FORMAT csv)" |
            psql_at "$site" -c "\copy $table FROM STDIN (FORMAT csv)"
    done
    psql_at "$site" -1 -v "site=$site" -v "site_no=${site_numbers[$site]}" -f sql/site_constraints.sql -f sql/site_views.sql -c 'ANALYZE;'
done
printf '%s\n' 'Reference and all four sites loaded.'
