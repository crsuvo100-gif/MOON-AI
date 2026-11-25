# MOON / HERMES — System Run Report

**Command:** `Run the system`
**Run time (UTC):** 2026-11-25 07:53–08:0x
**Status:** ✅ SYSTEM RUNNING — all services GREEN, all acceptance gates PASS

## 1. Live services

| Endpoint | HTTP | Result |
|---|---|---|
| `http://127.0.0.1:8777/api/interface/version` | 200 | `{"name":"MOON","version":"0.1.0","app":"MOON-AI"}` |
| `http://127.0.0.1:8777/hud` | 200 | `MOON-AI — NEURAL CORE` |
| `http://127.0.0.1:8777/api/health` | 200 | `HEALTHY` — 11/11 subsystems nominal |
| `http://127.0.0.1:11434/api/version` | 200 | Ollama 0.40.12 |
| `http://127.0.0.1:8644/health` | 200 | `{"status":"ok","platform":"webhook"}` |

Live processes: `uvicorn app.terminal_interface:app --port 8777`, `scripts/open_hud.py`,
`ollama serve`, `hermes gateway run`, `hermes_agent_control.py`, tmux session
`hermes-system` running `hermes chat`.

## 2. Acceptance gates

| Gate | Result |
|---|---|
| `moon version` | `moon-ai-agent 0.1.0` |
| `moon doctor` | PASS — Python 3.14.10, 41 agents, 40 tools, Ollama reachable, Git intact (2 benign first-run dir warnings) |
| `make build` | ✅ exit 0 — wheel `moon_ai_agent-0.1.0` built and installed |
| `make live` | ✅ exit 0 — 21/21 checks passed |
| `make test` | ✅ exit 0 — 1023 tests passed, 0 failed |

## 3. Repair applied this run

First `make live` attempt reached 20/21: `VS Code: 8 recommended extensions`
reported `extensions=6, languages=0`. `.vscode/extensions.json` had uncommitted
drift that dropped the ACP-client, GitHub, Thunder Client, GitLens and
black-formatter recommendations required by `tasks/MOON-BUILD.md`. Restored the
required recommendation set while preserving the newer `ruff`,
`mypy-type-checker` and `pylance-extended` entries and the
`unwantedRecommendations` block. No product code changed. Re-run: 21/21 PASS.

## 4. Entry points

1. Browser — `http://127.0.0.1:8777` → MOON-AI NEURAL CORE
2. CLI — `.venv/bin/moon` (`terminal`, `run`, `doctor`, `status`, `version`)
3. CLI — `.venv/bin/python main.py terminal`
