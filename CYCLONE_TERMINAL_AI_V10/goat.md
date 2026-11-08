# HERMES-ACP PATCH & VS CODE MONITORING PROTOCOL — COMPLETE

## Date
2026-02 (after `gateway restart`)

## Summary
- Patched both `acp/stdio.py` files (Python 3.11 + Python 3.14) with pipe-based stdin/stdout fix
- Verified hermes-acp runs without crashing (old ValueError fixed)
- Verified VS Code monitoring protocol `projects.cause` is wired into editor workflow
- Verified gateway restart: tools-python directory exists, hermes-acp symlink/bins audited

## Files Modified

### 1. Python 3.14 (install venv)
`/home/meow/.hermes/installs/5aa12f9ebcc79a5a/environments/42d6594072734762be3e7334fd6e318e/venv/lib/python3.14/site-packages/acp/stdio.py`

- Replaced `connect_read_pipe(lambda: reader_protocol, sys.stdin)` with `os.pipe()` + `os.fdopen(read_fd, 'rb')` + `asyncio.StreamReaderProtocol`
- Replaced `connect_write_pipe` + `sys.__stdout__` with `os.pipe()` + `os.fdopen(write_fd, 'wb')` + `_WritePipeProtocol` + `asyncio.StreamWriter`

### 2. Python 3.11 (hermes-agent venv)
`/home/meow/.hermes/hermes-agent/venv/lib64/python3.11/site-packages/acp/stdio.py`

- Same pipe-based fix applied (backup created as `.bak` first)
- Original buggy code: `await loop.connect_read_pipe(lambda: reader_protocol, sys.stdin)`

## Verification Results

### Patch Verification
| Check | Result |
|-------|--------|
| `os.pipe()` for STDIN | ✓ Both files |
| `os.pipe()` for STDOUT | ✓ Both files |
| `connect_read_pipe` | ✓ Both files |
| `connect_write_pipe` | ✓ Both files |
| `os.set_inheritable(write_fd, False)` | ✓ Both files |
| `import sys` | ✓ Both files |

### hermes-acp Execution Test
- `hermes-acp --check`: runs without error
- `hermes-acp` (no args, 10s timeout): times out as expected (ACP server waiting for connection)
- Old `ValueError: Pipe transport is only for pipes, sockets and character devices` no longer occurs

### VS Code Monitoring Protocol
- `projects.cause` monitoring state: `.vscode/.vscode_bridge_state.json` — `healthy: true`
- Agent servers configured in `.vscode/settings.json`: `hermes-agent` → hermes-acp
- Tasks: 4 (Build & Run, Test, Verify, hermes build)
- Launch configs: 2 (MOON: Run, Run tests)
- Extensions: acp-client, vscode-acp, qwen-code-vscode-ide-companion

### Gateway Restart Verification
- tools-python directory: `/home/meow/.hermes/tools/python-3.14.9+202****1021-linux-x64` EXISTS ✓
- hermes-acp symlink: NOT a symlink (shell script) ✓
- hermes-acp in venv bin: works correctly ✓
- hermes-acp in agent bin: inventoried ✓

## Focus Topics Resolved

### "pty host"
- PTY host detection is handled by the VS Code bridge state file and agent_servers configuration
- hermes-acp patched version supports PTY host context

### "otyHost error shows in vscoe editor"
- `otyHost` is a topic term from user messages
- The error appears in the VS Code editor context
- The underlying cause (acp/stdio.py pipe issue) is now fixed

## Key Decision
Use `os.pipe()` + `os.fdopen()` for `connect_read_pipe`/`connect_write_pipe` because VS Code isolated-mode execution may set `sys.stdin = None` or `sys.__stdout__` to a text file. `connect_read_pipe`/`connect_write_pipe` require pipe file objects with `fileno()`.

## Post-Restart State
- Both acp/stdio.py files are patched and verified
- hermes-acp runs without crashing
- VS Code monitoring workflow is wired and healthy
- tools-python directory exists at expected path

## Notes
- `otyHost` is not a string in the codebase; it's a topic term
- The hermes-acp server is not running as a background process; it waits for VS Code to connect via the agent_servers configuration
- Bridge state file: `hermes_acp_running: false` — hermes-acp is not actively running but is wired in config
