# MOON — Architecture

## Overview

The current MOON repository is a real Python application organized around the `app/` package rather than a single monolithic `engine.py` module. The verified runtime structure is a layered system made up of:

- root CLI bootstrap in `main.py`
- Python package entry wrappers in `moon/`
- application runtime packages under `app/`
- developer automation under `scripts/`, `Makefile`, and `deploy/`
- data and runtime state under project-local directories such as `data/`, `connections/`, and `.moon/`

```text
MOON/
├── main.py                  # CLI / bootstrap / service entry point
├── app/                     # active application implementation
│   ├── brain/               # orchestration, reasoning, and memory coordination
│   ├── config/              # settings, env, logging, and config helpers
│   ├── capability/          # capability registry + discovery
│   ├── connector/           # connection gateway and integration tools
│   ├── terminal/            # REPL / terminal UI / interactive runtime
│   ├── tools/               # tool definitions and execution wrappers
│   ├── models/              # model providers and adapters
│   ├── memory/              # persistence and retrieval logic
│   ├── context/             # session and conversation state
│   ├── verification/        # health and validation checks
│   └── ...
├── moon/                    # compatibility/bootstrap package for `python -m moon`
├── scripts/                 # setup and maintenance helpers
├── tests/                   # test suite and fixtures
├── docs/                    # architecture, config, install, and deployment notes
├── skills/                  # installed skill definitions and reusable automation
├── data/                    # runtime data
├── connections/             # connection metadata
├── capabilities/            # installed capability registry data
├── deploy/                  # service definitions and runtime deployment config
├── apps/                    # app-specific interfaces or variants
├── web/                     # web resources / UI assets
├── voices/                  # voice assets and related runtime files
├── plugins/                 # plugin entry points / generated runtime integration
├── build/                   # generated build artifacts
├── dist/                    # packaged distribution outputs
├── .github/                 # repo automation and contribution files
├── README.md                # project overview and startup instructions
├── pyproject.toml           # packaging metadata
├── Makefile                 # developer entry points
├── .env.example             # environment template
├── .gitignore               # local state exclusions
└── LICENSE                  # project license
```

---

## Agent Engine (`engine.py`)

The engine is the heart of MOON. On each request:

1. **Input Validation** — sanitize and validate the request
2. **Context Collection** — gather conversation history, memory, relevant tools
3. **Intent Understanding** — 13 personas, 13 intent routing rules
4. **Task Decomposition** — break complex requests into subtasks
5. **Planning** — create an execution plan
6. **Tool Selection** — choose appropriate tools from the registry
7. **Permission/Safety Check** — RUNLEVEL-based gating (SAFE → BLOCKED)
8. **Tool Execution** — execute selected tools
9. **Observation** — capture tool outputs
10. **Error Recovery** — retry, fallback, or escalate
11. **Result Verification** — confirm the result meets the request
12. **Memory Update** — store facts, lessons, outcomes
13. **Final Response** — return structured result to user

---

## Tool Registry

MOON has a three-tier tool architecture:

| Tier | File | Count | Description |
|------|------|-------|-------------|
| Core | `tools_core.py` | 14 | File ops, shell, git, HTTP, memory, search, eval |
| Professional | `tools_pro.py` | 52 | Task queue, workflow DAG, resources, chain, parallel, structured output, report, decision matrix |
| Advanced | `tools_advanced.py` | 22+ | Hermes bridge, web research, OSINT, code tools |

Each tool has: name, description, input schema, output schema, validation, permission level, timeout, error handling, logging.

---

## Memory System

Three layers:

1. **Conversation Memory** — in-memory, current session only
2. **Workspace Memory** — SQLite (`moon_memory.db`), persists across restarts
3. **Semantic Memory** — TF-IDF based retrieval over stored knowledge

Auto-learning is configurable: every interaction's facts, tool outcomes, and lessons can be consolidated into durable memory.

---

## Agent Architecture

MOON uses a main-agent + specialist-agents model:

- **Main Agent** — routes requests, chooses tools, coordinates
- **Planner** — decomposes complex tasks
- **Research Agent** — web research, OSINT
- **Coding Agent** — code generation, review, debugging
- **File Agent** — file operations, inspection
- **Automation Agent** — workflow execution, task queues
- **System Agent** — system info, service control
- **Web/API Agent** — HTTP, API interaction
- **Specialized Agents** — cyber, voice, creative, monitor, etc.

Specialist agents communicate through well-defined interfaces. The main agent coordinates rather than duplicating logic.

---

## Model Provider System

MOON uses Ollama as the primary local LLM provider:

- **OllamaClient** — speaks the Ollama REST API
- **Model selection** — per-agent model configuration
- **Fallback** — OpenAI-compatible API as secondary
- **No hard-coded keys** — all credentials via environment variables

---

## Interface Layer

| Interface | Entry Point | Description |
|-----------|-------------|-------------|
| CLI | `moon` or `python main.py` | Terminal-based interaction |
| REST API | `http://127.0.0.1:8777/api/...` | HTTP endpoints for integration |
| Web HUD | Browser → `http://127.0.0.1:8777` | Neural Brain Command Center (Three.js) |
| Voice | `make voice` | Typed/talked input → female voice output |

---

## Deployment

- **systemd user service** — auto-start, self-heal, deep monitoring every 15 min
- **Installer** — `install.sh` (bash) + `install_moon_full.py` (Python) handle everything
- **Port** — default `8777` (configurable via `MOON_PORT`)
