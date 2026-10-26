# MOON-AI Build — auto-generated for [python].
# Targets: run test build serve clean install verify
PY := env -u PYTHONPATH .venv/bin/python

.PHONY: help run test build serve clean install verify live

help:
	@echo "Targets: run test build serve clean install verify live"

run:
	$(PY) main.py run

test:
	$(PY) -m pytest tests -q

build:
	$(PY) -m pip install -e .

serve:
	python main.py terminal

clean:
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .mypy_cache .venv

install:
	$(PY) -m pip install -r requirements.txt
	$(PY) -m pip install -r requirements-optional.txt

verify:
	$(PY) scripts/live_smoke_pipeline.py

live:
	$(PY) scripts/live_smoke_pipeline.py
