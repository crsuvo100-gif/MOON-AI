# MOON — Status

> `status.md` was requested but did not exist in the repo, so this document is
> synthesised from the live backend health check (`python -m moon status`) plus
> git/data state. Backend: **HEALTHY**.

## Live backend — `127.0.0.1:8777`

| Category | Result |
|---|---|
| Overall | **HEALTHY** — "11/11 subsystems nominal" |
| Agent brains | **OK** — 41 connected |
| Tool registry | **OK** — 40 tools |
| Long-term memory | OK — 0 entries |
| Short-term memory | OK — 0 items |
| Episodic memory | OK — 0 episodes |
| Knowledge base | OK — 290 docs / 88466 vectors |
| Cognitive memory | OK — 3 records |
| Advanced memory | OK — session `session_1794` |
| Memory sync | OK — 0 pending / 0 conflicts |
| System health | OK — CPU 35.2% / RAM 64.3% |
| Lock state | OK — **unlocked** |

## Repo state

| Item | Value |
|---|---|
| Branch | `main` |
| Modified | `.vscode/settings.json` |
| Deleted | whole `CYCLONE_TERMINAL_AI_V10/` tree (files removed) |
| Recent commits | `test: bound output flood regression capture` · `chore: remove temporary audit artifacts` · `chore: complete project integration and validation` · `fix: complete inventory git-tracking audit; register voice path; migrate vscode settings key` |

## Runtime data

- `data/agents/agent_factory.db`, `data/agents/agent_registry`, `data/agents/staging`
- `data/executions.db`
- `.moon_sessions.json` (active session IDs present)
- `.moon_terminal_history.json` (last session: `echo test`, success)

## Notes

- `moon status` reports everything nominal; the DAW/Datawall backend is running.
- Long-term memory is empty and short/episodic memory hold nothing yet.
- `CYCLONE_TERMINAL_AI_V10/` files were deleted from the working tree — it is
  no longer part of the repo state.

## Next steps

See `.github/ISSUE_TEMPLATE/`, `docs/TASK_TRACKER.md` and `scripts/moon_workflow.py`
for active tasks / workflow definitions. To start something from this state,
pick a command from `moon --help` (e.g. `run`, `terminal`, `doctor`, `status`).
