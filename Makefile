SHELL := /bin/bash
.SHELLFLAGS := -euo pipefail -c
.DEFAULT_GOAL := up
MACHINE ?= A

.PHONY: up down data load test

up:
	@case "$(MACHINE)" in A|B|C) ;; *) echo 'MACHINE must be A, B or C' >&2; exit 2 ;; esac
	docker compose --profile $(MACHINE) up -d --build --wait

down:
	@case "$(MACHINE)" in A|B|C) ;; *) echo 'MACHINE must be A, B or C' >&2; exit 2 ;; esac
	@echo 'Removing project containers and data volumes on machine $(MACHINE).'
	docker compose --profile $(MACHINE) down -v

data:
	@if [[ -f data/lab/summary.json ]]; then \
		printf '%s\n' 'data/lab/summary.json exists; generation skipped.'; \
	else \
		PYTHONUTF8=1 python3 CS5104_Project_DataGen/de01_hospital/generate.py --size lab --out data/lab; \
	fi

load:
	bash scripts/load.sh

test:
	bash -n scripts/load.sh
	bash -n scripts/deploy.sh
	python3 -c 'import json, subprocess, tomllib; \
	config = tomllib.load(open("deploy.toml", "rb")); \
	compose = json.loads(subprocess.check_output(["docker", "compose", "--profile", "*", "config", "--format", "json"])); \
	assert compose["name"] == "cs5104final"; \
	assert set(compose["services"]) == set(config["sites"]) | {"ref"}; \
	assert all(compose["services"][name]["profiles"] == [site["machine"]] and int(compose["services"][name]["ports"][0]["published"]) == site["port"] and compose["services"][name]["environment"]["POSTGRES_DB"] == config["dbname"] for name, site in {**config["sites"], "ref": config["ref"]}.items())'
