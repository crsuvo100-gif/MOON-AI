# MOON-AI Build — auto-generated for [python].
# Targets: run test build serve clean install install-optional verify live
PY := env -u PYTHONPATH .venv/bin/python

.PHONY: help run test build serve clean install install-optional verify live

help:
	@echo "Targets: run test build serve clean install install-optional verify live"

run:
	$(PY) main.py run

test:
	$(PY) -m pytest tests -q

build:
	$(PY) -m pip uninstall -y moon-ai-agent 2>/dev/null || true
	$(PY) -m pip install . --no-deps --force-reinstall

# Serve the Neural Brain Command Center (web/API + WebSocket) on :8777.
# This is the same launch path the shipped systemd unit uses:
#   uvicorn app.terminal_interface:app --host 127.0.0.1 --port 8777
# (The interactive REPL is `make terminal` / `python -m moon terminal`.)
serve:
	$(PY) main.py terminal

clean:
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .mypy_cache .venv

# Core runtime dependencies only — required and must always succeed.
install:
	$(PY) -m pip install -r requirements.txt
	$(PY) -m pip install -e .

# Optional heavyweight extras (voice cloning / torch / telegram / browser).
# Best-effort: MOON degrades gracefully when these are absent.
install-optional:
	-$(PY) -m pip install -r requirements-optional.txt

verify:
	$(PY) scripts/live_smoke_pipeline.py

live:
	$(PY) scripts/live_smoke_pipeline.py
