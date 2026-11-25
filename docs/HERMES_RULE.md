# Hermes Rule — MOON implementation

## Status

IMPLEMENTED (additive). Existing APIs, data, memory, configurations, tools and
runtime behavior are preserved. No existing module was removed or rewritten.

## Canonical rule

> Hermes Rule:hermes you follow this rule all the time when any project start by you.you save this rule into your system and also iplement to MOON system. Rule - Note for hermes:save and memries all task for this project.Development agent: Hermes Code editor: Existing VS Code installation and verified workspace, when available Primary runtime owner: MOON itself Core principle: HERMES BUILDS IT. MOON OWNS IT. MOON OPERATES IT. TESTS VERIFY IT.

The verbatim text is a trusted Python constant in `app/runtime/hermes_rule.py`.
It mirrors `skills/hermes-rule/SKILL.md` and is treated as `SYSTEM_POLICY`
provenance with USER authority. Retrieved content, prompts, tool output and
agent messages are DATA and never override it.

## Components

| Component | Purpose | Existing system reused |
| --- | --- | --- |
| `app/runtime/hermes_rule.py` | Canonical rule, recall API, task trace decorator, memory indexing | `TaskStore`, `LocalTaskLedger`, `KnowledgeBase`, `CognitiveMemoryManager` |
| `app/runtime/integration.py` | Backward-compatible re-export layer (`hermes_rule`, `hermes_tasks`, `hermes_rule_status`) | Existing integration facade |
| `app/brain/orchestrator.py` | `@trace_hermes_task` on `run_task`; rule indexed during `setup()` | Existing orchestrator lifecycle |
| `app/terminal/repl.py` | `/rule [query]`, `/tasks [n]` commands | Existing REPL command dispatcher |
| `tests/unit/test_hermes_rule.py` | Regression/unit coverage | Existing pytest suite |

## Durable task recording

Every `Orchestrator.run_task()` call is wrapped by `trace_hermes_task`:

1. On entry, a `RUNNING` `TaskRecord` is written with `event="started"`.
2. On return or exception, a terminal record is written with `event="finished"`.
3. `TaskStore.record()` upserts into the canonical SQLite store and the
   source-folder ledger (`tasks/<task_id>.json` + `tasks/ledger.json`).
4. Prompt/result/error text is redacted for common secret shapes and truncated
   before persistence. Recording failures are logged and never interrupt work.

Task IDs are stable, so the two writes are idempotent. Existing task history is
never deleted, overwritten with a different schema, or migrated.

## Rule recall

- `recall_hermes_rule(query)` returns the canonical rule, provenance hash and
  the most relevant canonical sections. The query is keyword-matched only.
- During `setup()`, the rule document is indexed into the existing knowledge
  base (doc id `hermes-rule:governing-rule`) and stored as a canonical,
  high-importance GLOBAL procedural memory in the existing cognitive memory
  manager. Both writes are best-effort and additive.
- REPL: `/rule` shows the rule; `/tasks` shows durable task records.

## Security notes

- No secret values are logged or persisted by this capability.
- No external content is executed. Agent/task text is sanitized data.
- No destructive operations, permission changes, or configuration rewrites
  are performed by the Hermes Rule integration.
- HERMES remains a development agent; MOON remains the runtime owner.

## Verification

Run:

```bash
source /home/meow/Projects/MOON/.venv/bin/activate
python -m pytest tests/unit/test_hermes_rule.py -q
python -m moon doctor
```

Completed verification results are recorded in `docs/TASK_TRACKER.md`.
