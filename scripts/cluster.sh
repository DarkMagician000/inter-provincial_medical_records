#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

action=${1-}
case "$action" in
    all|site-down|site-up) ;;
    *) printf 'Usage: bash scripts/cluster.sh all|site-down|site-up [site]\n' >&2; exit 2 ;;
esac

targets=$(python3 - "$action" "${2-}" <<'PY'
import ipaddress
import re
import sys
import tomllib

with open("deploy.toml", "rb") as source:
    config = tomllib.load(source)
action, site = sys.argv[1:]
if action == "all":
    machines = ("B", "C")
    site = "-"
else:
    if site not in {"tayninh", "hcm", "cantho", "dongnai"}:
        raise ValueError("SITE must be tayninh, hcm, cantho or dongnai")
    machines = (config["sites"][site]["machine"],)
for machine in machines:
    if machine not in {"A", "B", "C"}:
        raise ValueError(f"Invalid machine: {machine!r}")
    settings = config["machines"][machine]
    address = ipaddress.ip_address(settings["ip"])
    user = settings["ssh_user"]
    if not isinstance(user, str) or not re.fullmatch(r"[a-z_][a-z0-9_-]*", user):
        raise ValueError(f"Invalid ssh_user for {machine}")
    print(machine, f"{user}@{address}", site, sep="\t")
PY
)

while IFS=$'\t' read -r machine host site; do
    if [[ "$action" == all ]]; then
        printf 'Deploying to machine %s (%s)\n' "$machine" "$host"
        tar -cz --exclude='./data' --exclude='.git' --exclude='./results' --exclude='*.pdf' --exclude='*/output' . |
            ssh "$host" 'mkdir -p ~/cs5104_final && tar -xz -C ~/cs5104_final'
    else
        runner=()
        if [[ "$machine" != A ]]; then
            runner=(ssh "$host")
        fi
        "${runner[@]}" bash -s -- "$action" "$site" <<'SH'
set -euo pipefail
container="final_$2"
if [[ "$1" == site-down ]]; then
    docker stop "$container"
else
    docker start "$container"
    deadline=$((SECONDS + 30))
    while (( SECONDS < deadline )); do
        if docker exec "$container" pg_isready -U postgres -d hospital -t 1 >/dev/null 2>&1; then
            printf '%s ready\n' "$container"
            exit 0
        fi
        sleep 1
    done
    printf '%s not ready after 30 seconds\n' "$container" >&2
    exit 1
fi
SH
    fi
done <<< "$targets"

if [[ "$action" == all ]]; then
    while IFS=$'\t' read -r machine host site; do
        ssh -n "$host" "cd ~/cs5104_final && make up MACHINE=$machine"
    done <<< "$targets"
fi
