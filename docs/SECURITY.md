# MOON — Security Guide

## Security Model

MOON is designed to operate within a defined **safety boundary**. By default, MOON is authorized to act on systems and targets that belong to the operator. Actions against non-owned targets require explicit authorization.

### Safety Boundary

The safety boundary is configured in `.env` via `MOON_SAFETY_boundary`. This defines the scope within which MOON may operate autonomously. Targets outside this boundary are blocked unless explicitly authorized.

### RUNLEVEL Gating

MOON uses a RUNLEVEL system to gate capabilities:

| RUNLEVEL | Description |
|----------|-------------|
| `SAFE` | Read-only, informational, no side effects |
| `ANALYZE` | Analysis and assessment, no exploitation |
| `AUTHORIZED_OPS` | Active operations against authorized targets only |
| `BLOCKED` | Capabilities blocked entirely |

---

## What MOON Can Do

### Within Safety Boundary (Authorized)

- Network scanning (port scans, service enumeration) on owned infrastructure
- Vulnerability analysis on owned systems
- Web research and OSINT on public information
- File operations on local files
- Code generation and execution (with sandboxing where applicable)
- API interaction (with explicit authorization)
- Voice interaction
- Memory consolidation and learning

### Blocked by Default

- Actions against non-owned targets without explicit authorization
- Exploitation of systems the operator does not own
- Any action the operator has not explicitly allowed
- Hard-coded credentials or secrets
- Unauthorized data exfiltration

---

## Security Features

### No Hard-Coded Secrets

All credentials are environment variables. `.env` is git-ignored. The setup wizard prompts for required configuration without storing secrets in the repo.

### Connector Egress and Agent Credentials

The connection gateway applies the same egress policy to agent delegation,
connection checks, and health probes. No public host, loopback, or private
address is implicitly trusted. Only exact hosts explicitly listed in
`ALLOWED_EGRESS_HOSTS` are auto-allowed; all other destinations require
operator confirmation. Model-generated tool arguments cannot supply that
confirmation: `ToolManager` overwrites the `confirmed` argument using its
separate trusted `operator_confirmed` signal. The gateway REST API counts a
confirmation only when a terminal access token is configured and the request
is authenticated. Until a user-facing approval flow is connected, configure
only the specific hosts required by the operator.
Disconnecting a saved connection also requires the trusted caller's explicit
operator-confirmation signal; a model-supplied argument cannot authorize it.
The gateway REST disconnect endpoint also requires a configured terminal token,
an authenticated request, and explicit `confirmed: true`; it fails closed when
operator authentication is not configured.

Agent capability manifests are versioned, size- and complexity-bounded
declarations. They are claims supplied during connection registration, not
proof that a peer supports a capability and not a grant of permissions or
egress. Only the supported `openai-chat-completions` protocol is accepted by
this manifest contract. Capability input/output schemas use a bounded JSON
Schema subset; legacy agent records without manifests remain valid. Inspecting
a saved manifest does not contact the peer. Explicit discovery requests fetch
`/.well-known/moon-agent.json` from an already registered agent only after the
normal egress check. Redirects and credential forwarding are disabled, the
response must be JSON and is capped at 32 KiB, and invalid manifests do not
replace a prior declaration. DNS is not pinned to the address used by the HTTP
client, so DNS rebinding is not fully mitigated. Discovery verifies the
manifest's shape, not the peer's identity or claimed behavior; live network
discovery was not exercised during this validation.

For OpenAI-compatible peer agents, `credential_ref` names an environment
variable. Its value is used as a bearer token at request time and is not stored
in the connection record. An unset reference means no Authorization header is
sent. Inline MCP environment values are runtime-only: connection serialization
omits them, and legacy persisted inline values are ignored with a warning. Put
secrets in the MOON process environment rather than connection metadata. Agent
and MCP health checks perform real protocol requests rather than reporting
success based only on a configured URL. MCP stdio connections require an
explicit command and never install or launch an implicit package.
Connection registry updates are written to a same-directory temporary file and
atomically replaced; a failed write preserves the previous registry file.

Agent tasks can be submitted through the `global_connector` tool's `submit`
action or the authenticated `POST /gateway/connections/{name}/tasks` route.
Both use the same process-wide gateway and egress policy; the REST route returns
an opaque task ID, and `GET /gateway/tasks/{task_id}` (or the tool's
`task_status` action) returns bounded status and result data. The local,
git-ignored `connections/agent_tasks.json` stores at most 100 records with
owner-only file permissions. Prompts and system instructions are not persisted;
peer answers are retained up to 8,000 characters, so results may still contain
sensitive data and should be treated as local private data. Peer answers are
untrusted content and must not override MOON's policies or independently
authorize further actions. Active tasks are marked interrupted after a process
restart and are never automatically replayed. At most eight tasks can be queued
or running at once.

When an agent has a declared manifest, tasks must name one of its declared
capabilities and provide structured input matching its input schema. The peer
response must be valid JSON matching its declared output schema and the result
size limit or the task is marked failed. This checks data shape only; it does
not verify agent identity, truthfulness, or that the peer actually performs the
declared work. Legacy agents without a manifest retain prompt-based delegation.

### Permission Levels on Tools

Every tool has a permission level. The engine checks permissions before executing tools. High-risk tools require elevated RUNLEVEL.

### Capability Sandbox Limitations

`SandboxExecutor` prefers bubblewrap, Podman, or Docker. Its `workspace` fallback
is not an isolation boundary: it executes locally, does not disable network
access, and does not confine filesystem writes. The fallback removes
non-allowlisted environment variables, applies a timeout, and caps captured
stdout/stderr at 1 MB per stream. Its install helpers refuse to run through the
workspace fallback. Capability acquisition through the package manager
requires an explicit confirmation callback, but package installation can
execute third-party scripts with the current account's privileges. Do not run
untrusted code using the workspace fallback.

### Active-Operation Authorization and Local Data Tools

Active target operations require a host/IP explicitly listed in
`AUTHORIZED_TARGETS`, a matching configured CIDR, or a literal boolean runtime
confirmation. Loopback and private-network addresses are not implicitly
authorized. The SQLite tool accepts `SELECT` queries against a read-only
connection; the file manager refuses to overwrite an existing file unless an
explicit `overwrite=true` argument is supplied and confines resolved paths to
its configured root. Reads are capped at 4,000 characters, directory listings at
200 entries, and writes at 1 MB. File writes use a same-directory temporary
file and atomic replace for explicit overwrites; create-only writes use an
atomic hard link so an existing destination is never replaced.
Database queries are capped at 10,000 characters, 50 rows, and 20,000
characters of returned text; SQLite VM work is interrupted after its step or
time budget. Where the Python SQLite API supports connection limits, result
value and column limits are also applied.
PDF, OCR and image tools resolve input files within their configured workspace
and reject files larger than 20 MiB. Image processing and OCR reject images
over five million pixels; OCR has a five-second processing timeout. Resized
images are dimension-bounded, size-checked, and created atomically without
overwriting an existing output.
Local espeak/SoX TTS rejects text over 2,000 characters, runs outside the async
event loop with a 60-second subprocess timeout, checks generated audio files,
and removes partial outputs on failure.
Optional microphone transcription accepts only 1–15-second recordings, finalizes
the Vosk result, and closes the audio stream and temporary recording on success
or failure. This API has fake-device tests; microphone hardware and recognition
model behavior have not been tested.
The Python executor and system-command tool are dangerous capabilities and
must remain behind the tool approval gate. Their child processes have bounded
execution time and captured output, and POSIX process groups are terminated on
completion or timeout; this is resource control, not an OS sandbox, and code
still runs with the MOON process account's filesystem and network permissions.

### Memory Backup Files

Memory backup names are restricted to simple filename-safe identifiers and
backup creation uses an atomic create-only write, so an existing snapshot is
not silently replaced. Retention is bounded to 1–100 files. JSON/JSONL exports
are atomic and do not overwrite existing files unless explicitly requested;
imports are limited to 50 MiB, 100,000 records, and 100,000 characters per
content/summary field.

### ACP Agent Processes

The optional ACP connector launches its configured agent as a local subprocess.
It advertises no client filesystem or terminal methods, sends no MCP servers,
rejects permission requests without an approval UI, and bounds protocol output.
ACP is not an operating-system sandbox: an agent process still has the
permissions of its OS account. Do not configure or launch an untrusted
executable; delegation is opt-in through the `moon acp ... --confirm` operator
CLI. It may invoke configured external providers. The command is not available
as a model-facing tool/API.

### Browser and Search Egress

Web search requires operator confirmation unless its provider is in
`ALLOWED_EGRESS_HOSTS`; a model-supplied `confirmed` argument is ignored by the
tool dispatcher. Browser navigation accepts only HTTP(S), checks the
destination's resolved addresses, and applies the same permission gate to each
HTTP request and redirect. Private or unallowlisted destinations require
operator confirmation; JavaScript and service workers are disabled during
extraction. DNS is checked before navigation but is not IP-pinned, so this is
risk reduction rather than complete SSRF protection. Search results include
source links but remain untrusted content and must be cross-checked before
being treated as facts.

The current browser tool is read-only: it extracts up to 2,000 characters of
page text with JavaScript disabled. It does not expose screenshots, mouse or
keyboard input, form submission, or general computer-use actions. The browser
agent manifest is limited to navigation and page reading; broader computer-use
capabilities remain unimplemented.

### Input Validation

All inputs are validated before processing. Malformed or suspicious inputs are rejected.

### Error Handling

Errors are logged, never silently swallowed. Failures are reported to the user.

### Audit Logging

All tool executions, agent actions, and significant events are logged for audit purposes.

---

## Securing Your MOON Installation

### 1. Configure the Safety Boundary

On first run, the setup wizard asks for your safety boundary. Set this to your organization/domain.

### 2. Protect .env

```bash
chmod 600 .env
```

`.env` contains your API keys and configuration. Keep it private.

### 3. Run as a Non-Root User

MOON runs as a user service (systemd `--user`). It should never run as root.

### 4. Network Exposure

By default, MOON binds to localhost (127.0.0.1). Do not expose the API port to the public internet without authentication.

### 5. Model Isolation

MOON uses Ollama for local inference. Ollama runs locally and should not be exposed publicly.

---

## Security Audit

A security audit of MOON's codebase is conducted as part of the build process. The audit covers:

- Hard-coded secrets and credentials
- Input validation gaps
- Permission bypass vulnerabilities
- Unsafe execution paths
- Data exposure risks
- Insecure defaults

See the compilation document (`MOON_WHOLE_PROJECT_INSIGHT.md`) for the full security audit findings.

---

## Responsible Use

MOON is a powerful tool. Use it responsibly:

- Only scan systems you own or have explicit permission to test
- Only access data you are authorized to access
- Only run operations within your safety boundary
- Report findings responsibly

MOON is designed for authorized security work, research, automation, and productivity. It is not designed for unauthorized access, data theft, or malicious activity.
