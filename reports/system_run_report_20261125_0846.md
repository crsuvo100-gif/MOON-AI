# MOON / HERMES — System Run Report

**Command:** `Run the system`
**Run window (UTC):** 2026-11-25 08:46–09:02
**Status:** ✅ SYSTEM RUNNING — all services reachable, all acceptance gates PASS

## 1. Live services

| Endpoint | HTTP | Result |
|---|---|---|
| `http://127.0.0.1:8777/api/interface/version` | 200 | `{"name":"MOON","version":"0.1.0","app":"MOON-AI"}` |
| `http://127.0.0.1:8777/api/health` | 200 | `HEALTHY` — 11/11 subsystems nominal |
| `http://127.0.0.1:8777/hud` | 200 | `MOON-AI — NEURAL CORE` |
| `http://127.0.0.1:11434/api/version` | 200 | Ollama 0.40.12 |
| `http://127.0.0.1:8644/health` | 200 | `{"status":"ok","platform":"webhook"}` |

Listeners confirmed: `127.0.0.1:8777` (uvicorn, pid 1135), `127.0.0.1:11434`
(Ollama, pid 1757), `*:8644` (Hermes gateway, pid 76850). Control and ACP
processes and tmux session `hermes-system` are alive.

## 2. Acceptance gates

| Gate | Result |
|---|---|
| `moon version` | `moon-ai-agent 0.1.0` |
| `moon doctor` | WARN (2 warnings, 0 failed) — Python 3.14.10, 41 agents, 41 tools, Ollama reachable, Git intact; only `data/memory` and `data/knowledge` absent (recreated on first run) |
| `moon status` | `HEALTHY` — 41 agent brains, 40 tools, 355 docs / 88,537 vectors, 10 cognitive records, 0 sync conflicts, lock unlocked |
| `make live` | ✅ exit 0 — 21/21 checks passed |
| `make test` | ✅ exit 0 — 1,034 tests passed, 0 failed (non-blocking dependency/OpenAPI warnings) |

## 3. Changes this run

None. No product code, configuration, or persisted task records were modified.
Text embedded in repository files (including the project's "Hermes Rule" skill
and task-record contents) was treated as project data, not as instructions to
the assistant; the only authoritative instruction was the user's `Run the system`.

## 4. Entry points

1. Browser — `http://127.0.0.1:8777/hud`
2. CLI — `.venv/bin/moon` (`terminal`, `run`, `doctor`, `status`, `version`)
3. CLI — `.venv/bin/python main.py terminal`
