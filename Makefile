# MOON AI Agent -- Makefile
#
# Common entry points. Run `make help` for the list.

PY := env -u PYTHONPATH .venv/bin/python

.PHONY: help run serve terminal test live voice-test voice voice-install models clean install start deploy build lint format check

help:
	@echo "Targets: run serve terminal test live voice-test voice voice-install models install start deploy build lint format check"
	@echo "  install   - install Ollama systemd service (sudo make install)"
	@echo "  start     - launch MOON (ensures Ollama is up first)"
	@echo "  build     - build wheel + sdist into dist/ and refresh the editable install"
	@echo "  build-clean - remove dist/, *.egg-info, .eggs/ and caches"
	@echo "  lint      - run the ruff lint pass (informational; warnings do not block builds)"
	@echo "  format    - run the ruff format pass (informational; diff only, does not block builds)"
	@echo "  check     - run the mypy + ruff quality gate (informational)"
	@echo "  deploy    - install the systemd service units"
	@echo "  install   - install Ollama systemd service (sudo make install)"
	@echo "  start     - launch MOON (ensures Ollama is up first)"

run:
	$(PY) main.py run "$(TASK)" --agent $(AGENT)

serve:
	python3 scripts/moon_launcher.py terminal

terminal:
	python3 scripts/moon_launcher.py terminal

install:
	@echo "== Installing Ollama service (model backend for MOON) =="
	@python3 scripts/install_ollama.py

start:
	@python3 scripts/moon_launcher.py $(MODE)

test:
	$(PY) -m pytest tests -q

live:
	$(PY) scripts/live_smoke_pipeline.py

voice-test:
	$(PY) -c "import asyncio; from app.voice import Voice; w=asyncio.run(Voice(preset='seductive').speak('Hello, I am MOON.')); print('female voice WAV:', w)"

voice:
	$(PY) scripts/voice_loop.py

models:
	$(PY) main.py models

voice-install:
	$(PY) install_moon.py

# ---- Build & quality gates -------------------------------------------------
build:
	$(PY) -m pip install --upgrade pip wheel
	$(PY) -m pip wheel --no-deps --no-build-isolation -w dist/ .
	$(PY) -m pip install --force-reinstall --no-deps --no-build-isolation -e . 2>/dev/null || $(PY) -m pip install -e .
	@echo "Built wheel(s):"
	ls -1 dist/*.whl 2>/dev/null || true
	@echo "Built sdist:"
	ls -1 dist/*.tar.gz 2>/dev/null || true

build-clean:
	rm -rf dist *.egg-info .eggs .ruff_cache .mypy_cache
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +

lint:
	$(PY) -m ruff check . --output-format=concise || true
	@echo "  lint: informational - warnings are advisory, they do not block builds"

format:
	$(PY) -m ruff format . --diff || true
	@echo "  format: informational - diff only, does not block builds"

check:
	$(PY) -m mypy main.py app --ignore-missing-imports --show-error-codes 2>/dev/null || true
	$(PY) -m ruff check . --output-format=concise || true

# ---- MOON workflow runner: save-first source folder + auto-build + GitHub-complete
workflow:
	$(PY) scripts/moon_workflow.py run $(TASK)

auto-work:
	$(PY) scripts/moon_workflow.py run $(TASK)

# ---- Save the current build/work product into the MOON source folder
save:
	$(PY) scripts/moon_workflow.py run cp -r . $(MOON_SRC)/

clean:
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .mypy_cache
