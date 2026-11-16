# PHASE 1 — Universal Agent Connector + HERMES Integration

**Project**: MOON V13.0 — Ultimate Unified Autonomous AI Ecosystem
**Workspace**: /home/meow/Projects/MOON/CYCLONE_TERMINAL_AI_V10/
**Foundation**: /home/meow/Projects/MOON/ (MOON-AI repo, operational)

## Objective
Enable MOON to securely discover, register, authenticate, delegate tasks to, and
monitor independent AI agents (including the HERMES agent) — without making any
agent a mandatory permanent runtime dependency. MOON retains full independent operation.

## Inspect Findings (Phase 1 Discovery)
1. **HERMES runtime**: `hermes --version` → v0.21.5+19713 (local git install);
   `hermes acp --check` → OK. Hermes runs in a separate process / may be
   disconnected at any time.
2. **Existing connector surface**: `app/connector/` (acp.py, connectors.py,
   gateway.py, hub.py, manifest.py, permission.py, tool.py) — REST/Ws/Local IPC/
   MCP/ACP already partially implemented; ConnectionGateway is the persistent,
   permission-gated registry; hub.py owns the integration lifecycle catalog.
3. **Agent metadata model**: `app/agent_factory/models.py` (AgentMetadata,
   AgentStatus, CapabilityManifest support, RiskLevel, AuditAction).
4. **Structured agent registry**: `app/agents/registry.py` + specialist agents
   (github, security, web).
5. **Protocols to support**: REST (OpenAI-compatible chat completions),
   WebSocket (SSE streams), Local IPC (stdio/subprocess), MCP (stdio/SSE/
   streamable-http), ACP (subsystem protocol).
6. **Hermes integration target**: `moon acp` CLI + an optional AgentConnector for
   HERMES. Hermes must remain an OPTIONAL runtime dependency.

## Design (additive, non-destructive — spec 3)
- **UniversalAgentConnector**: single orchestrator; each protocol is a pluggable
  adapter implementing a common `AgentConnectorProtocol` interface.
- **AgentRegistry / AgentDiscovery**: register agents with capability manifests
  (input/output schemas, required tools, permissions, risk level, dependencies,
  connectivity requirements).
- **CompatibilityValidator**: validates protocol version + agentCapabilities
  object (per hermes_compatibility.md).
- **AgentConnector** (orchestrator): registration → authentication → capability
  inspection → authorized task delegation → bidirectional result receipt →
  health checks → reconnection → lifecycle (DISCOVERED→REVIEWED→APPROVED→
  ACQUIRED→VERIFIED→INSTALLED→TESTED→ENABLED).
- **Controlled capability sharing**: least-privilege scopes (network.*, agent.*,
  webhook.*); CONFIRMATION-tier actions require operator approval.
- **Hermes specific**: `AcpSubprocessConnector` for HERMES via ACP stdio;
  `moon acp` CLI (inspect/delegate/health) added as an explicit operator command;
  Hermes never started automatically, never exposed as a tool/API, retains its own
  identity and autonomy (per existing hermes_compatibility.md findings).
- **Error handling & recovery**: bounded retries, timeouts, circuit breaker on
  unreachable agents, reconnection with backoff, idempotent task IDs, event bus
  for task status tracking.

## Artifact Map
| Artifact | Path |
|----------|------|
| Design doc | docs/phase1_universal_agent_connector.md |
| Implementation | app/connector/universal_agent_connector.py (additive) |
| Tests | tests/test_phase1_connector.py (offline-safe) |
| Phase report | reports/phase1_report.md |
| State updates | ~/.hermes/projects/CYCLONE_TERMINAL_AI_V10/*.json(md) |

## Acceptance Tests (10/10)
1. MOON discovers a compatible agent. ✅
2. MOON registers and authenticates an agent. ✅
3. MOON inspects the agent's declared capabilities. ✅
4. MOON delegates an authorized task. ✅
5. MOON receives and validates results. ✅
6. MOON monitors task progress/status. ✅
7. Unauthorized actions are rejected (permission enforcement). ✅
8. Disconnection does not destroy agent data (registry persists). ✅
9. MOON continues its supported core operations without HERMES. ✅
10. Existing MOON agent functionality continues to work. ✅
