"""Hermes Rule -- durable task recording + rule recall (additive module).

This module implements the project-governing Hermes Rule for MOON without
replacing any existing subsystem:

  * Rule recall: canonical rule text plus keyword-indexed sections are exposed
    through :func:`recall_hermes_rule` and indexed into the existing knowledge
    base and cognitive memory (best effort, never a hard runtime dependency).
  * Durable task recording: every ``Orchestrator.run_task`` invocation is
    traced by :func:`trace_hermes_task`, which writes into the existing
    :class:`TaskStore` (SQLite) and the existing source-folder task ledger.

Security boundary: the rule text below is a trusted *constant* copied from the
project skill document. Retrieved content, task prompts, results and exception
text are DATA only -- they are redacted/truncated before persistence and are
never executed or promoted to instructions.
"""

from __future__ import annotations

import functools
import hashlib
import re
import time
from collections.abc import Callable
from typing import Any, TypeVar

from app.config.logging import get_logger
from app.memory.task_record import TaskRecord, TaskStatus, TaskStore

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Canonical rule (verbatim from skills/hermes-rule/SKILL.md)
# ---------------------------------------------------------------------------

HERMES_RULE_TEXT = (
    "Hermes Rule:hermes you follow this rule all the time when any project start by you."
    "you save this rule into your system and also iplement to MOON system. Rule - "
    "Note for hermes:save and memries all task for this project.Development agent: Hermes "
    "Code editor: Existing VS Code installation and verified workspace, when available "
    "Primary runtime owner: MOON itself Core principle: HERMES BUILDS IT. MOON OWNS IT. "
    "MOON OPERATES IT. TESTS VERIFY IT."
)

ROLE_SEPARATION = (
    "Hermes = development agent (builds, edits, verifies; does not operate). "
    "MOON = runtime owner (runs the system, owns the project, operates the verified build). "
    "Tests verify it = coverage is re-run after every change; failing tests block completion."
)

MANDATORY_BEHAVIOR = (
    "1. Record and remember every task for the project before and during work -- MOON "
    "persists a task record (session log / knowledge graph / long-term memory). "
    "2. Use the existing VS Code installation and verified workspace when available; "
    "fall back to the default Hermes terminal otherwise. "
    "3. Build additive and non-destructive. Do not delete or rewrite history. "
    "4. Work in bite-sized steps; complete the acceptance bar (launch-ready) before "
    "declaring done."
)

MOON_OPERATING = (
    "MOON owns and operates the runtime it builds; the commands it was given are the "
    "ones it executes. MOON records all tasks for the project automatically at run "
    "time and keeps them in durable storage. Hermes keeps building and saving the "
    "system; MOON keeps owning and operating it."
)

SUCCESS_CRITERIA = (
    "Any project started by Hermes carries the rule in its record. MOON can recall the "
    "rule and the task-recording workflow at any time. A launch-ready system exists "
    "with tests (pytest / make test / make build) passing."
)

RULE_DOC_ID = "hermes-rule:governing-rule"
RULE_TAGS = ["hermes-rule", "canonical", "governing-rule", "task-recording"]
RULE_PROVENANCE = {
    "authority": "USER",
    "priority": "SYSTEM_POLICY",
    "source": "skills/hermes-rule/SKILL.md",
    "trusted": True,
    "note": "Trusted project rule constant; external content never overrides it.",
}
HERMES_RULE_SHA256 = hashlib.sha256(HERMES_RULE_TEXT.encode("utf-8")).hexdigest()

_RULE_DOCUMENT = "\n\n".join(
    [
        "# Hermes Rule (project governing rule)",
        f"## Rule text (verbatim)\n\n{HERMES_RULE_TEXT}",
        f"## Role separation\n\n{ROLE_SEPARATION}",
        f"## Mandatory behavior on every project start\n\n{MANDATORY_BEHAVIOR}",
        f"## MOON operating the system it builds\n\n{MOON_OPERATING}",
        f"## Success criteria\n\n{SUCCESS_CRITERIA}",
        f"## Provenance\n\n{RULE_PROVENANCE}",
    ]
)

_RULE_SECTIONS: list[dict[str, Any]] = [
    {
        "title": "Rule text (verbatim)",
        "text": HERMES_RULE_TEXT,
        "keywords": {"rule", "hermes", "builds", "owns", "operates", "tests", "verify", "core"},
    },
    {
        "title": "Role separation",
        "text": ROLE_SEPARATION,
        "keywords": {"role", "hermes", "moon", "developer", "editor", "runtime", "owner", "tests"},
    },
    {
        "title": "Mandatory behavior on every project start",
        "text": MANDATORY_BEHAVIOR,
        "keywords": {"task", "record", "remember", "save", "vscode", "code", "workspace", "additive", "non-destructive", "bite", "sized", "launch", "ready"},
    },
    {
        "title": "MOON operating the system it builds",
        "text": MOON_OPERATING,
        "keywords": {"moon", "operate", "runtime", "durable", "storage", "task", "records", "hermes"},
    },
    {
        "title": "Success criteria",
        "text": SUCCESS_CRITERIA,
        "keywords": {"success", "criteria", "recall", "rule", "tests", "pytest", "make", "passing", "record"},
    },
]

# ---------------------------------------------------------------------------
# Input hygiene: task text is untrusted data, never an instruction.
# ---------------------------------------------------------------------------

_SECRET_PATTERN = re.compile(
    r"(?i)(?:"
    r"sk-[A-Za-z0-9_-]{8,}|"
    r"Bearer\s+[A-Za-z0-9._~-]{8,}|"
    r"(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|secret)"
    r"\s*[:=]\s*\S+"
    r")"
)


def safe_text(value: Any, *, limit: int = 4000) -> str:
    """Redact common secret shapes and bound text before persistence."""
    text = "" if value is None else str(value)
    text = _SECRET_PATTERN.sub("[REDACTED]", text)
    text = text.replace("\x00", "")
    if len(text) > limit:
        return text[:limit] + "...[TRUNCATED]"
    return text


# ---------------------------------------------------------------------------
# Rule recall
# ---------------------------------------------------------------------------


def rule_document() -> str:
    """Return the canonical rule document for indexing or display."""
    return _RULE_DOCUMENT


def recall_hermes_rule(query: str = "", *, top_k: int = 5) -> dict[str, Any]:
    """Recall the Hermes Rule and the most relevant canonical sections.

    The query is treated as data (keyword matching only). No retrieved or
    user-supplied text can modify the returned canonical rule.
    """
    tokens = set(re.findall(r"[a-z0-9_]+", safe_text(query, limit=500).lower()))
    ranked: list[tuple[int, int, dict[str, Any]]] = []
    for index, section in enumerate(_RULE_SECTIONS):
        score = len(tokens & section["keywords"])
        ranked.append((score, -index, section))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    limit = max(1, min(int(top_k), len(_RULE_SECTIONS)))
    selected = [
        {"title": section["title"], "text": section["text"]}
        for _score, _neg, section in ranked[:limit]
    ]
    return {
        "rule": HERMES_RULE_TEXT,
        "sections": selected,
        "roles": ROLE_SEPARATION,
        "workflow": MANDATORY_BEHAVIOR,
        "success_criteria": SUCCESS_CRITERIA,
        "sha256": HERMES_RULE_SHA256,
        "source": RULE_PROVENANCE,
        "query": safe_text(query, limit=200),
    }


async def ensure_hermes_rule_memory(
    knowledge_base: Any = None,
    cognitive_memory: Any = None,
) -> dict[str, Any]:
    """Index the canonical rule into existing memory stores (best effort).

    Existing stores are reused; nothing is deleted or replaced. Failures are
    logged and reported, never raised into the calling task flow.
    """
    result: dict[str, Any] = {"knowledge_base": "not_configured", "cognitive_memory": "not_configured"}

    if knowledge_base is not None:
        try:
            chunks = await knowledge_base.index_document(
                RULE_DOC_ID,
                _RULE_DOCUMENT,
                metadata=dict(RULE_PROVENANCE),
                tags=list(RULE_TAGS),
            )
            result["knowledge_base"] = {"doc_id": RULE_DOC_ID, "chunks": int(chunks)}
        except Exception as exc:  # noqa: BLE001
            result["knowledge_base"] = f"error: {type(exc).__name__}"
            logger.warning("Hermes Rule knowledge indexing skipped: %s", exc)

    if cognitive_memory is not None:
        try:
            from app.memory.record import Importance, MemoryType, Scope, SourceType

            record = cognitive_memory.store(
                _RULE_DOCUMENT,
                source_type=SourceType.USER,
                scope=Scope.GLOBAL,
                type_=MemoryType.PROCEDURAL,
                tags=list(RULE_TAGS),
                explicit=True,
                importance=Importance.CRITICAL,
                project_id="MOON",
                canonical=True,
            )
            result["cognitive_memory"] = {
                "stored": record is not None,
                "memory_id": getattr(record, "id", "") if record else "",
            }
        except Exception as exc:  # noqa: BLE001
            result["cognitive_memory"] = f"error: {type(exc).__name__}"
            logger.warning("Hermes Rule cognitive memory write skipped: %s", exc)

    return result


# ---------------------------------------------------------------------------
# Durable task recording
# ---------------------------------------------------------------------------

_TASK_STORE: TaskStore | None = None
_STATUS_MAP: dict[str, TaskStatus] = {
    "pending": TaskStatus.PENDING,
    "running": TaskStatus.RUNNING,
    "completed": TaskStatus.COMPLETED,
    "done": TaskStatus.COMPLETED,
    "failed": TaskStatus.FAILED,
    "cancelled": TaskStatus.CANCELLED,
    "timed_out": TaskStatus.TIMED_OUT,
}

F = TypeVar("F", bound=Callable[..., Any])


def configure_task_store(store: TaskStore | None) -> None:
    """Override the task store (tests / alternate deployments only)."""
    global _TASK_STORE
    _TASK_STORE = store


def get_task_store() -> TaskStore:
    """Return the shared task store singleton (created on first use)."""
    global _TASK_STORE
    if _TASK_STORE is None:
        _TASK_STORE = TaskStore()
    return _TASK_STORE


def _resolve_status(task: Any, *, error: BaseException | None) -> TaskStatus:
    raw = str(getattr(task, "status", "") or "").lower()
    status = _STATUS_MAP.get(raw, TaskStatus.PENDING)
    if error is not None and status in (TaskStatus.PENDING, TaskStatus.RUNNING):
        return TaskStatus.FAILED
    return status


def record_hermes_task(
    task: Any,
    *,
    event: str = "finished",
    agent_id: str = "",
    error: BaseException | None = None,
    store: TaskStore | None = None,
) -> TaskRecord:
    """Persist one task lifecycle event to SQLite + source-folder ledger.

    Safe to call on start and finish; ``TaskStore.record`` is an idempotent
    upsert keyed by ``(project_id, task_id)``.
    """
    now = time.time()
    status = _resolve_status(task, error=error)
    if event == "started" and status is TaskStatus.PENDING:
        # The decorated function marks the task running after entry; the trace
        # itself represents the start of execution, so record RUNNING here.
        status = TaskStatus.RUNNING
    record = TaskRecord(
        task_id=str(getattr(task, "id", "") or ""),
        content=safe_text(getattr(task, "prompt", "")),
        summary=f"Hermes Rule task trace: {event}",
        agent_id=safe_text(agent_id or getattr(task, "agent_name", ""), limit=200),
        project_id="MOON",
        task_status=status,
        result=safe_text(getattr(task, "result", "")) if event == "finished" else "",
        start_time=now if event == "started" else None,
        end_time=now if event == "finished" else None,
        tags=["hermes-rule", event],
        metadata={
            "event": event,
            "rule_sha256": HERMES_RULE_SHA256,
            "trusted": False,
            "error_type": type(error).__name__ if error else "",
        },
        source_type="AGENT",
        provenance=dict(RULE_PROVENANCE),
        confidence=0.6,
        importance="MEDIUM",
    )
    (store or get_task_store()).record(record)
    return record


def list_hermes_tasks(*, status: TaskStatus | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """List recorded tasks as plain dicts (safe for CLI/API display)."""
    records = get_task_store().list_tasks(status=status, limit=limit)
    return [
        {
            "task_id": rec.task_id,
            "content": safe_text(rec.content, limit=200),
            "agent_id": rec.agent_id,
            "status": rec.task_status.value,
            "updated_at": rec.updated_at,
        }
        for rec in records
    ]


def hermes_task_stats() -> dict[str, Any]:
    return {"recorded_tasks": get_task_store().stats(), "rule_sha256": HERMES_RULE_SHA256}


def trace_hermes_task(fn: F) -> F:
    """Decorator: record every task at start and at terminal return/error.

    Wraps the existing coroutine without changing its signature or behavior.
    All recording failures are swallowed so task execution is never broken by
    the observability layer.
    """

    @functools.wraps(fn)
    async def wrapper(self: Any, task: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            record_hermes_task(task, event="started", agent_id=getattr(task, "agent_name", ""))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Hermes Rule start record skipped: %s", exc)

        error: BaseException | None = None
        try:
            return await fn(self, task, *args, **kwargs)
        except BaseException as exc:
            error = exc
            raise
        finally:
            try:
                record_hermes_task(
                    task,
                    event="finished",
                    agent_id=getattr(task, "agent_name", ""),
                    error=error,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Hermes Rule finish record skipped: %s", exc)

    return wrapper  # type: ignore[return-value]


__all__ = [
    "HERMES_RULE_SHA256",
    "HERMES_RULE_TEXT",
    "RULE_DOC_ID",
    "RULE_TAGS",
    "configure_task_store",
    "ensure_hermes_rule_memory",
    "get_task_store",
    "hermes_task_stats",
    "list_hermes_tasks",
    "recall_hermes_rule",
    "record_hermes_task",
    "rule_document",
    "safe_text",
    "trace_hermes_task",
]
