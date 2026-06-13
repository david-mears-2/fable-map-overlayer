VENV := .venv
PY := $(VENV)/bin/python

$(VENV)/.ok: requirements.txt
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -q -r requirements.txt
	touch $(VENV)/.ok

venv: $(VENV)/.ok

fetch: venv
	$(PY) -m src.fetch

grid: venv
	$(PY) -m src.grid

layers: venv
	$(PY) -m src.layers.parks

score: venv
	$(PY) -m src.score

deploy:
	cp output/grid.json ../web/public/grid.json
	@echo "deployed output/grid.json -> web/public/grid.json"

all: fetch grid layers score deploy

.PHONY: venv fetch grid layers score deploy all
