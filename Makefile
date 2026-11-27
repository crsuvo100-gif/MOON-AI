# MOON-AI Build — professionally reconfigured (additive; original header kept).
# ---------------------------------------------------------------------------
# Every original target/recipe below is preserved. New targets are additions.
#
# Recommended build sequence (also driven by `make agents`, one role at a time):
#   make install   -> tools + core/optional deps + editable install + editor tooling
#   make build     -> build and install the project package
#   make arrange   -> ensure the full project file/folder layout exists
#   make compile   -> byte-compile every Python source in the project
#   make verify    -> end-to-end live smoke verification (post-build, pre-serve)
#   make serve     -> launch the project (interactive terminal REPL)
#
# Shortcuts:
#   make agents        run all agent roles one by one (build/edit/rum/run/verify)
#   make pipeline      install -> build -> arrange -> compile -> verify-full
#   make release       pipeline -> serve
# ---------------------------------------------------------------------------
PY := env -u PYTHONPATH .venv/bin/python
CODE := code

.PHONY: help run test build serve clean install install-optional verify live \
        bootstrap editor-tools install-ollama arrange compile tree \
        agents agent-build agent-edit agent-rum agent-run agent-verify \
        verify-full pipeline release serve-web

help:
	@echo "MOON-AI targets (original): run test build serve clean install install-optional verify live"
	@echo "MOON-AI targets (added):    bootstrap editor-tools install-ollama arrange compile tree agents agent-build agent-edit agent-rum agent-run agent-verify verify-full pipeline release serve-web"
	@echo "Build sequence: make install -> make build -> make arrange -> make compile -> make verify -> make serve"
	@echo "All agents, one by one: make agents     |   Everything: make release"

# --- bootstrap --------------------------------------------------------------
# Create the project virtualenv if it is missing. Never touches an existing one.
bootstrap:
	@if [ ! -x .venv/bin/python ]; then echo "[setup] creating .venv"; python3 -m venv .venv; fi
	$(PY) -m pip --version

# --- run (original) ----------------------------------------------------------
run:
	$(PY) main.py run

# --- test (original) ---------------------------------------------------------
test:
	$(PY) -m pytest tests -q

# --- build (original) --------------------------------------------------------
build:
	$(PY) -m pip uninstall -y moon-ai-agent 2>/dev/null || true
	$(PY) -m pip install . --no-deps --force-reinstall

# Serve the Neural Brain Command Center (web/API + WebSocket) on :8777.
# This is the same launch path the shipped systemd unit uses:
#   uvicorn app.terminal_interface:app --host 127.0.0.1 --port 8777
# (The interactive REPL is `make terminal` / `python -m moon terminal`.)
serve:
	$(PY) main.py terminal

# Optional web/API serve path (additive; does not change `serve`).
serve-web:
	$(PY) -m uvicorn app.terminal_interface:app --host 127.0.0.1 --port 8777

clean:
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .mypy_cache .venv

# --- install (original core steps preserved, tooling added) -----------------
# Core runtime dependencies only — required and must always succeed.
install: bootstrap
	$(PY) -m pip install -r requirements.txt
	$(PY) -m pip install -e .
	@echo "[install] core runtime installed"
	@$(MAKE) --no-print-directory editor-tools

# Recommended code-editor / developer tooling. Best-effort: a missing network
# or a missing VS Code CLI cannot break the core install.
editor-tools:
	-$(PY) -m pip install --upgrade pip wheel setuptools
	-$(PY) -m pip install ruff mypy black pylint
	@if command -v $(CODE) >/dev/null 2>&1; then \
	  echo "[editor] installing recommended VS Code extensions"; \
	  $(CODE) --install-extension ms-python.python \
	          --install-extension ms-python.vscode-pylance \
	          --install-extension charliermarsh.ruff \
	          --install-extension ms-python.black-formatter \
	          --install-extension ms-python.mypy-type-checker \
	          --install-extension ms-python.debugpy \
	          --install-extension eamodio.gitlens \
	          --install-extension github.vscode-pull-request-github \
	          --install-extension formulahendry.acp-client \
	          --install-extension omercnet.vscode-acp \
	          --install-extension rangav.vscode-thunder-client \
	          --install-extension tamastro.pylance-extended >/dev/null 2>&1 || true; \
	else echo "[editor] VS Code CLI not found; skipped extension install"; fi

# Optional heavyweight extras (voice cloning / torch / telegram / browser).
# Best-effort: MOON degrades gracefully when these are absent.
install-optional:
	-$(PY) -m pip install -r requirements-optional.txt

# Local model runtime. Kept separate so `make install` never needs sudo.
install-ollama:
	-$(PY) scripts/install_ollama.py

# --- arrange ----------------------------------------------------------------
# Ensure every expected project folder exists. Additive only: creates missing
# folders and .gitkeep markers; never moves, renames or deletes existing files.
arrange:
	@mkdir -p app/agents/professional app/agents/advanced app/agents/specialist \
	  app/brain/advanced app/context/advanced app/memory/advanced \
	  app/skills/advanced app/config app/data app/logs \
	  agent moon scripts tools tests docs reports verify \
	  web apps plugins deploy terminal skills voices tasks connections
	@for d in app/data app/logs reports verify connections plugins/generated; do \
	  if [ -d "$$d" ] && [ ! -e "$$d/.gitkeep" ]; then touch "$$d/.gitkeep"; fi; \
	done
	@echo "[arrange] project folder layout verified (nothing removed)"
	@$(MAKE) --no-print-directory tree

tree:
	@echo "--- MOON-AI top-level layout ---"
	@find . -maxdepth 1 -mindepth 1 \
	  ! -name .git ! -name .venv ! -name build ! -name '__pycache__' \
	  ! -name '*.egg-info' | sort

# --- compile ----------------------------------------------------------------
# Full-project byte compilation. Excludes virtualenv, build output and .git.
compile: arrange
	@echo "[compile] byte-compiling all project Python sources"
	$(PY) -m compileall -q -f -x '(\.venv|/build/|/\.git/|/\.pytest_cache/)' .
	@echo "[compile] OK"

# --- verify (original preserved) --------------------------------------------
verify:
	$(PY) scripts/live_smoke_pipeline.py

live:
	$(PY) scripts/live_smoke_pipeline.py

# Deeper verification: compile + full pytest suite + live smoke pipeline.
verify-full: compile
	$(PY) -m pytest tests -q
	$(PY) scripts/live_smoke_pipeline.py

# --- agents: every role, one by one -----------------------------------------
# The named roles map to real stages: build / edit(arrange) / rum(run,compile)
# / run(test+verify) / verify. `make agents` executes them strictly in order.
agents:
	$(PY) scripts/moon_agents.py

agent-build:
	$(MAKE) build

agent-edit:
	$(MAKE) arrange

agent-rum:
	$(MAKE) compile

agent-run:
	$(MAKE) test

agent-verify:
	$(MAKE) verify

# --- ordered end-to-end pipeline --------------------------------------------
pipeline:
	$(MAKE) install
	$(MAKE) build
	$(MAKE) arrange
	$(MAKE) compile
	$(MAKE) verify-full

release: pipeline
	$(MAKE) serve
