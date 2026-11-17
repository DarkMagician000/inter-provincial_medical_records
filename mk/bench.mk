ifndef PY
PY ?= $(shell test -x $$HOME/cs5104-venv/bin/python && echo $$HOME/cs5104-venv/bin/python || echo python3)
endif

.PHONY: bench delay-on delay-off

bench:
	$(PY) scripts/bench.py

delay-on:
	bash scripts/delay.sh on 30

delay-off:
	bash scripts/delay.sh off
