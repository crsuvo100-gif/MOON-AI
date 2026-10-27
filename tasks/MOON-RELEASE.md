# MOON — v0.1.0 (Launch-Ready) Release

Repository: https://github.com/crsuvo100-gif/MOON-AI
Tag:    v0.1.0
Commit: 45955cc "build: wire VS Code tasks.json + hermes ACP + moon-vscode extension; final E2E verification; launch-ready"

## What shipped
- VS Code workspace wired: `.vscode/tasks.json` (Build&Run / Test / Verify / hermes acp),
  `.vscode/extensions.json` (moon-vscode: acp-client, acp, github, thunder-client, gitlens,
  ms-python), `.vscode/settings.json` + `.vscode/launch.json`.
- hermes ACP server: `hermes acp` starts the ACP adapter (env from ~/.hermes/.env, foreground
  stdio JSON-RPC) — frontend (VS Code ACP client) -> hermes acp -> hermes gateway.
- End-to-end verified (real execution):
  - Browser :8777 -> /hud -> `MOON-AI — NEURAL CORE`
  - Server :8777 `/api/interface/version|models|terminal/agents|capabilities|tools` -> all exit 0
  - `make run` (41 agent brains, real LLM call, RESULT correct), `make test` (98 tests,
    exit 0), `make live` (21/21 checks, exit 0)
  - `moon terminal` + `./venv/bin/python main.py terminal` REPL clean
- Task build artifacts saved to source folder: `tasks/MOON-BUILD.md`, `tasks/TEST-001.json`,
  `tasks/ledger.json`.

## Acceptance bar (launched)
- deps installed and proven by real execution
- frontend + backend wired with real verified interaction
- SAVE AND PUSH TO REPO gate: commit + push to origin main succeeded (git push exit 0)

## Entry points
1. `http://127.0.0.1:8777` (browser)
2. `moon terminal`
3. `./venv/bin/python main.py terminal`
   Unlocks with phrase: `MOON love you 3000`
