#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 || ! ${2:-30} =~ ^[0-9]+$ ]]; then
    printf 'Usage: bash scripts/delay.sh on|off [ms=30]\n' >&2
    exit 2
fi
case "$1" in
    on|off) ;;
    *) printf 'Expected on or off.\n' >&2; exit 2 ;;
esac

tc_at() {
    docker exec final_tayninh tc "$@"
}

if error=$(tc_at qdisc del dev eth0 root 2>&1); then
    :
elif [[ $error != *'No such file or directory'* && $error != *'Cannot delete qdisc with handle of zero'* ]]; then
    printf '%s\n' "$error" >&2
    exit 1
fi

if [[ $1 == on ]]; then
    trap 'tc_at qdisc del dev eth0 root >&2 || true' EXIT
    tc_at qdisc add dev eth0 root handle 1: prio bands 3 priomap 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0
    tc_at qdisc add dev eth0 parent 1:3 handle 30: netem delay "${2:-30}ms"
    # Remote published ports from deploy.toml: hcm, cantho, dongnai; keep in sync.
    for port in 5434 5435 5436; do
        tc_at filter add dev eth0 protocol ip parent 1: prio 1 u32 \
            match ip protocol 6 0xff match ip dport "$port" 0xffff flowid 1:3
    done
fi

tc_at qdisc show dev eth0
tc_at filter show dev eth0
trap - EXIT
