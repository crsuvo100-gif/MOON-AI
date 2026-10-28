# MOON Capability Digital Twin

## Project Overview
- **Root**: /home/meow/Projects/MOON
- **Branch**: feat/repl-version-command
- **Package**: moon-ai-agent 0.1.0 (setuptools/pip)
- **Entry**: main.py (CLI entrypoint)
- **Build**: Makefile (run, test, build, serve, clean, install, verify, live)
- **Language**: Python 3.10+
- **Runtime**: .venv/bin/python (virtual env, 7.1G, gitignored)

## Component Inventory
### Directories
- app/ (33 dirs) — 344 .py files; core runtime modules
- tests/ (45 .py) — pytest suite
- scripts/ (20 .py) — utility scripts
- skills/ (275 .md) — skill corpus
- tools/ (37 .py) — command-line tools
- apps/ (cyclone, moon_ui) — MI applications
- connections/ — registry.json, README.md
- .moon/ — knowledge_graph.json, sessions
- data/ — executions.db, agents, README.md
- voices/ — alice.wav, alice.txt, registry.json, README.md
- tasks/ — tasks
- web/ — user interface
- deploy/ — deployment artifacts
- dist/ — build artifact

### Key Files
- main.py — CLI entrypoint (24470 bytes)
- Makefile — build targets
- pyproject.toml — package config
- .env.example — 4048 bytes environment template
- .gitignore — excludes .venv/, capabilities/installed/, connections/registry.json, data/, dist/, deploy/, home/, plugins/, logs/, scripts/logs/, tasks/completed/, web/dist/
- .env — environment configuration (gitignored)
- .vscode/settings.json — modified: python.defaultInterpreterPath = .venv/bin/python
- .vscode/extensions.json — 10 recommendations, 1 language
- .vscode/launch.json — 2 configurations (Run application, Run tests)
- .vscode/tasks.json — 4 tasks: MOON: Build & Run, MOON: Test, MOON: Verify, hermes build
- tools/vscode/moon-vscode — bash launcher script (code-oss)
- tools/vscode/settings.json — VS Code settings (old python.pythonPath = /usr/bin/python3)

## Capabilities Map
| Capability | Implementation | Agent | Tool | Model | Provider | Dependencies | Permissions | Health | Status |
|------------|---------------|-------|------|-------|----------|-------------|-------------|--------|--------|
| Main brain (memory + knowledge) | LongTermMemory + KnowledgeBase | orchestrator | — | Ollama/cloud | local + cloud | — | network.agent | HEALTHY | WORKING |
| Per-agent brains (39 agents) | Isolated memory per agent | orchestrator + agents | — | Ollama/cloud | local + cloud | — | network.agent | HEALTHY | WORKING |
| Autonomous self-learning | enable_auto_learning | orchestrator | — | Ollama/cloud | local + cloud | — | — | HEALTHY | WORKING |
| Neural Brain Command Center | Three.js web UI | — | — | — | — | — | — | HEALTHY | WORKING |
| Terminal UI (Textual) | Textual TUI | — | — | — | — | — | — | HEALTHY | WORKING |
| GitHub auto-pull | connected repo | moon_local agent | — | — | — | — | network | HEALTHY | WORKING |
| Female voice (espeak + sox) | voice module | — | — | — | — | espeak, sox | — | HEALTHY | WORKING |
| FastAPI API | app/api/interface.py | — | — | — | — | fastapi, uvicorn | — | HEALTHY | WORKING |
| WebSocket events | app/api/terminal.py | — | — | — | — | flask-socketio | — | HEALTHY | WORKING |
| Model routing (3-tier fallback) | llm_service + fallback | orchestrator | — | — | local + cloud | — | network | HEALTHY | WORKING |
| Voice cloning (F5-TTS/kokoro) | voice module + torch | — | — | — | cloud | torch, torchaudio | — | HEALTHY | WORKING |
| Tool acquisition | app/capability/installer.py | tool_acquisition agent | — | — | GitHub | — | network | HEALTHY | WORKING |
| HFOV (hardened) | hardening_audit_tool | — | — | — | — | — | — | HEALTHY | WORKING |
| Vulnerability scanner | vuln_scanner_tool | — | — | — | — | — | — | PARTIAL | WORKING |
| GitHub sync | github_sync_tool | — | — | — | — | — | network | HEALTHY | WORKING |
| Model management | model_management_tool | — | — | — | — | — | — | HEALTHY | WORKING |
| Self-evolution | self_evolve_tool | — | — | — | — | — | — | HEALTHY | WORKING |
| Sandbox (filesystem, limits, policies) | sandbox/ | — | — | — | — | — | — | HEALTHY | WORKING |
| Capability registry | app/capability/registry.py | — | — | — | — | — | — | HEALTHY | WORKING |
| Integration hub | app/connector/hub.py | — | — | — | — | — | — | HEALTHY | WORKING |
| Connection gateway | app/connector/gateway.py | — | — | — | — | — | — | HEALTHY | WORKING |
| Security (authorization) | app/security/ | — | — | — | — | — | — | HEALTHY | WORKING |
| Voice engine | app/voice.py | — | — | — | — | espeak, sox, kokoro | — | HEALTHY | WORKING |
| Knowledge graph | .moon/knowledge_graph.json | — | — | — | — | — | — | HEALTHY | WORKING |
| Conversation sessions | .moon/sessions | — | — | — | — | — | — | HEALTHY | WORKING |
| Execution database | data/executions.db | — | — | — | — | sqlite | — | HEALTHY | WORKING |
| Ollama backend | Ollama + cloud fallbacks | orchestrator | — | — | local:11434 | — | network | HEALTHY | WORKING |
| Dark/Light HUD UI | apps/moon_ui | — | — | — | — | — | — | HEALTHY | WORKING |
| CLI (moon version, doctor, run, terminal) | main.py | — | — | — | — | — | — | HEALTHY | WORKING |
| VS Code integration | tools/vscode/ | — | — | — | — | code-oss | — | HEALTHY | WORKING |
| Agent OS (lifecycle, identity, state, resource) | app/agent_factory, app/agents | — | — | — | — | — | — | HEALTHY | WORKING |
| Knowledge provenance | app/knowledge/ | — | — | — | — | — | — | HEALTHY | WORKING |
| Cognitive memory | app/memory/ | — | — | — | — | — | — | HEALTHY | WORKING |
| Authorization engine | app/security/ | — | — | — | — | — | — | HEALTHY | WORKING |
| Policy engine | app/security/ | — | — | — | — | — | — | HEALTHY | WORKING |
| Observability stack | app/verification/ | — | — | — | — | — | — | HEALTHY | WORKING |
| Evidence engine | app/verification/ | — | — | — | — | — | — | HEALTHY | WORKING |
| Recovery engine | app/verification/ | — | — | — | — | — | — | HEALTHY | WORKING |
| Self-healing | app/verification/ | — | — | — | — | — | — | HEALTHY | WORKING |
| Cost-aware model routing | app/agent_factory | — | — | — | — | — | — | HEALTHY | WORKING |
