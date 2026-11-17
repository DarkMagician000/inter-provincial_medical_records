#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

up=false
hosts=()
for argument in "$@"; do
    case "$argument" in
        --up) up=true ;;
        cs-a|cs-b|cs-c) hosts+=("$argument") ;;
        *) printf 'Usage: bash scripts/deploy.sh [--up] [cs-a cs-b cs-c]\n' >&2; exit 2 ;;
    esac
done
if (( ${#hosts[@]} == 0 )); then
    hosts=(cs-a cs-b cs-c)
fi

for host in "${hosts[@]}"; do
    printf 'Deploying to %s\n' "$host"
    tar -cz --exclude='./data' --exclude='.git' --exclude='*.pdf' --exclude='*/output' . |
        ssh "$host" 'mkdir -p ~/cs5104_final && tar -xz -C ~/cs5104_final'
    if "$up"; then
        machine=${host#cs-}
        ssh "$host" "cd ~/cs5104_final && make up MACHINE=${machine^^}"
    fi
done
