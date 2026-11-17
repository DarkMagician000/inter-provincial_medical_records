PY ?= $(shell test -x $$HOME/cs5104-venv/bin/python && echo $$HOME/cs5104-venv/bin/python || echo python3)

.PHONY: dash
dash:
	$(PY) scripts/dashboard.py
