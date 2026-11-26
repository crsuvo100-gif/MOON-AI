# MOON -- Neural Brain Command Center

A self-hosted autonomous AI agent with its own "brain", connected per-agent
brains, and continuous self-learning. MOON provides a brain-connected terminal
REPL and an optional browser HUD at `http://127.0.0.1:8777/ui` when its HTTP
server is running.

## Features
- **Main brain (LongTermMemory + KnowledgeBase)** -- durable, survives restarts.
- **Per-agent brains** -- 39 specialist agents, each with its own isolated memory connected to the main brain.
- **Connected-agent tasks** -- permission-gated peer task submission with bounded, persistent status/result records; prompts are not persisted.
- **Autonomous self-learning** -- every interaction's facts, tool outcomes, and lessons are consolidated into the durable brain (`enable_auto_learning`).
- **Browser HUD** -- single-page canvas visualization with API status and a WebSocket event connection.
- **GitHub integration** -- optional repository search and on-demand file/tool retrieval; inspect fetched code before enabling or executing it.

## Voice capabilities

Voice helpers are implemented in `app/voice.py` and `app/voice_engine.py`, but
the CLI and Makefile do not currently expose a standalone voice workflow.
Microphone hardware, installed speech providers, and end-to-end voice
conversation have not been verified.

## Quick start

### Starting the terminal interface

The following commands launch the brain-connected terminal REPL:

```bash
python -m moon terminal
```

Running `python -m moon` without arguments launches the same REPL. To submit a
single task instead, use `python -m moon run "Your task"`.


```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env
make serve          # interactive terminal REPL

# Optional HTTP API and browser HUD:
.venv/bin/python -m uvicorn app.terminal_interface:app --host 127.0.0.1 --port 8777
# Open http://127.0.0.1:8777/ui
```

> ### GitHub login prompt when cloning? (read this)
> MOON has **no password or login screen**. If `git clone` asks for
> `Username for 'https://github.com'` / `Password`, that is **Git/GitHub's own
> credential prompt** — triggered by the repo's **visibility**, which only the
> repo owner can change on GitHub. Nothing in MOON controls it. To clone from
> GitHub with no (or minimal) friction, pick ONE:
> 1. **Make the repo PUBLIC** (GitHub → repo Settings → Danger Zone → Change
>    visibility → Public). Then `git clone https://github.com/crsuvo100-gif/MOON-AI.git`
>    works with **no credentials at all**. This is the only way to get a truly
>    password-free install.
> 2. **Use SSH** (recommended for private repos): `git clone
>    git@github.com:crsuvo100-gif/MOON-AI.git`. Add your SSH key to GitHub
>    (Settings → SSH and GPG keys) — no password needed afterward.
> 3. **Use HTTPS + a PAT**: username = your GitHub login (`meow`); password =
>    a **Personal Access Token** (GitHub disabled account-password git auth in
>    2021). Create one at GitHub → Settings → Developer settings → PATs.
## Configuration (`.env`)
| Key | Default | Purpose |
|-----|---------|---------|
| `MODEL_BASE_URL` | `http://127.0.0.1:11434/v1` | OpenAI-compatible local endpoint |
| `MODEL_NAME` | `qwen3:0.6b` | model id |
| `ENABLE_AUTO_LEARNING` | `true` | MOON learns from every interaction |
| `ENABLE_AGENT_VALIDATION` | `true` | two-phase main-brain validation |
| `GITHUB_REPO` | `https://github.com/crsuvo100-gif/MOON-AI` | connected repo for auto tool-pull |

## Tests
```bash
make test
```

---

## Python-First Architecture & Portability

MOON is a **Python-first** application. The core (orchestrator, agents, tools,
memory, model layer, services, terminal/UI, APIs) is implemented in Python and
runs on any machine with a compatible Python. Shell scripts (`install.sh`,
`start.sh`, `scripts/*.sh`, `Makefile`) are **optional convenience/bootstrap
wrappers only** — the real application is always launched through Python.

### Requirements
| Requirement | Minimum | Recommended |
|-------------|---------|-------------|
| Python | 3.10 | 3.11+ (3.13 tested) |
| OS | Linux, macOS, Windows | Linux (Debian/Ubuntu/Kali), macOS, Windows 10+ |
| CPU arch | x86_64, arm64 | x86_64 or arm64 |
| RAM | 4 GB | 8 GB+ |
| Storage | 2 GB (code + deps) | 10 GB+ (with models) |
| Network | localhost model endpoint OR cloud API | both |
| GPU | optional | optional (CPU works; GPU accelerates local models) |

MOON uses `pathlib`, `platform`, and `sys` for portable paths/OS detection;
there are **no hard-coded `/home/meow`, Kali, or Linux-only paths** in the core.
The only OS-specific code is `app/capability/installer.py`, which is a
**multi-platform package-manager abstraction** (apt/dnf/pacman/apk) — preserved
exactly as designed.

### Model dependencies
MOON talks to an **OpenAI-compatible** endpoint. Options:
- **Local** (default, CPU-friendly): [Ollama](https://ollama.com) serving
  `qwen3:0.6b`, `qwen2.5:3b`, `qwen2.5-coder:1.5b`, etc. Start Ollama, then
  `ollama pull qwen3:0.6b`.
- **Cloud**: set `OPENAI_API_KEY` / `OPENROUTER_API_KEY` / `HUGGINGFACE_API_KEY`
  in `.env` for the hosted fallback chain.

### Install (Python)
```bash
git clone git@github.com:crsuvo100-gif/MOON-AI.git
cd MOON
python -m venv .venv && .venv/bin/pip install -e .
cp .env.example .env          # then fill in secrets (NEVER commit .env)
python -m moon install        # bootstrap venv + deps + (best-effort) models
```

### Commands (all Python — `python -m moon <cmd>`)
| Command | Purpose |
|---------|---------|
| `python -m moon` | Launch the default Terminal/Neural Command Center UI |
| `python -m moon run "task"` | Run a single task and exit (a task is required) |
| `python -m moon doctor` | Health check (Python/deps/config/DB/agents/tools/model/git) → PASS/WARN/FAIL |
| `python -m moon status` | Check the live backend `/api/health` |
| `python -m moon backup` | Snapshot runtime data into `backups/moon_<ts>/` (cross-platform) |
| `python -m moon restore <snapshot>` | Restore without replacing existing runtime files |
| `python -m moon restore <snapshot> --confirm-overwrite` | Restore and replace conflicting runtime files after review |
| `python -m moon install` | Python bootstrap installer (venv + deps + models) |
| `python -m moon update` | Safe update: `git pull --ff-only` + `pip install -e . --upgrade` |
| `python -m moon models` | Pre-pull per-agent preferred models |
| `python -m moon telegram` | Telegram bot listener |
| `python -m moon version` | Print version |

Restore refuses to replace existing runtime files by default. Review the
snapshot and pass `--confirm-overwrite` to replace conflicting files; restore
merges the selected runtime paths and does not delete unrelated live files.

> The installed `moon` console script (`pyproject.toml [project.scripts]`) also
> works after `pip install -e .`.

### Recovery workflow (clean compatible machine)
```bash
git clone git@github.com:crsuvo100-gif/MOON-AI.git
cd MOON
python -m venv .venv && .venv/bin/pip install -e .
cp .env.example .env            # supply real secrets
python -m moon install          # venv + dependencies (+ local models if Ollama present)
python -m moon doctor           # verify the machine is ready
python -m moon                  # launch -> complete MOON (agents, tools, services, UI)
```
Runtime data (`data/`, `capabilities/`, `connections/`, `*.db`) is **not**
committed to Git (see `.gitignore`); it is recreated on first run and can be
restored from a `python -m moon backup` snapshot. Secrets (`.env`) and model
files are never committed.

### Backup / Restore
```bash
python -m moon backup           # -> backups/moon_YYYYMMDD_HHMMSS/
python -m moon restore backups/moon_YYYYMMDD_HHMMSS
```
Backups capture agents, knowledge, memory, skills, evaluations, logs, the
`agent_factory.db` and `executions.db`. They **exclude** `.env` (secrets) by
design — back that up separately.

# MOON — Standalone AI Agent System

A self-contained AI agent system. Runs on its own port (:8778), its own
virtualenv, and its own codebase. Fully independent — no connection to any
other project.

## What it is

- **8 agent personas**: general, code, security, research, voice, admin, creative, monitor
- **Real LLM integration**: Ollama-backed (OpenAI-compatible) on localhost:11434.
  Models: qwen3:0.6b (default), qwen3:1.7b, qwen2.5:1.5b/3b, deepseek-r1:1.5b/8b, and more.
  Configurable via env: `MOON_MODEL`, `MOON_OLLAMA_URL`,
  `MOON_TEMPERATURE`, `MOON_MAX_TOKENS`, `MOON_TIMEOUT`.
- **Tool-calling**: LLM decides when to call tools (file_read, file_write, shell,
  network_scan, system_info, etc.) and receives results back — multi-step reasoning.
- **Streaming**: WebSocket `/api/ws` streams tokens as the LLM generates.
- **Per-prompt agent selection**: `agent:<name> <message>` prefix syntax
- **Intent→agent routing**: keyword-based automatic routing
- **47 tools**: system_info, memory_read, memory_write, network_scan, security_tools,
  file_read, file_write, shell, web_search, web_extract, python_executor,
  system_command, docker, github_feed, tool_acquire, self_evolve, reflect,
  plan, log_reader, http_request, git_ops, email_sender, archive, dns_lookup,
  template_render, data_viz, encryption, data_export, yaml_ops, qr_generator,
  rest_api_framework, pdf_reader, ocr, image_processing, browser, preprocess,
  ssh_client, geoip_lookup, password_strength, steganography, cve_search,
  malware_scan, threat_intel, authorized_scan, recon_report, packet_capture,
  port_scanner
- **SQLite-backed session memory**
- **Hermes-desktop-terminal replica TUI**: interactive REPL with command palette
- **REST + WebSocket API**: `/api/moon-agent` on port :8778

## Entry points

```bash
moon_twin                 # Interactive terminal REPL
moon_twin --list          # List all agents
moon_twin --route "query" # Show which agent handles a query
moon_twin "message"       # Process a single message (non-interactive)
moon_twin --json "msg"    # JSON output mode
moon_twin --agent code "write hello"  # Force a specific agent
moon_twin_api             # Start /api/moon-agent server on :8778
moon_twin_api --test      # Run API self-test
```

## API endpoints (port :8778)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/moon-agent` | List all agents |
| POST | `/api/moon-agent` | Process a message |
| GET | `/api/moon-agent/route?query=<q>` | Route a query |
| GET | `/api/moon-agent/agents` | List agents (alias) |
| GET | `/api/moon-agent/memory` | Get memory |
| POST | `/api/moon-agent/memory` | Set memory |
| WS | `/api/ws` | Real-time WebSocket |

## Layout

```
Moon_Twin/
├── main.py              # CLI entry point (moon_twin)
├── agent/
│   ├── engine.py        # Agent engine: personas, routing, tools, real LLM
│   ├── api.py           # Starlette ASGI API server (/api/moon-agent)
│   ├── llm.py           # OllamaClient: LLM integration + tool-calling + streaming
│   └── memory.py        # SQLite session memory store
├── terminal/
│   └── app.py           # Hermes-desktop-terminal replica TUI
├── .venv/               # Python virtualenv (gitignored)
├── requirements.txt     # Dependencies
└── README.md
```

## Dependencies

- Python 3.10+
- `rich` — terminal UI
- `starlette` + `uvicorn` — ASGI API server
- `websockets` — WebSocket client/server
- `openai` — Ollama-compatible client
- Python stdlib: `asyncio`, `socket`, `sqlite3`, `subprocess`, `platform`

## Separation

MOON's code imports **only from itself** (`agent.engine`, `terminal.app`).
It does not import from any external project.
MOON runs on `127.0.0.1:8778`.
