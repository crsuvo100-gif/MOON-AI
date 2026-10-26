"""task_record.py -- task lifecycle record (spec 61/62/63).

Pure conversion layer between :class:`TaskRecord` (the in-memory task
contract) and the durable :class:`MemoryRecord` (SQLite). Stores raw facts only;
no routing, no retrieval -- that is :class:`MemoryStore`'s job.

Spec 88 boundaries are respected explicitly:
    MEMORY != DATABASE   (this is the record; the store is app/memory/store.py)
    MEMORY != CONTEXT    (context assembly lives in the ContextEngine)
    MEMORY != TRUSTED INSTRUCTION (see `trusted`: retrieved memory is DATA)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TYPE_CHECKING

from app.memory.record import Scope
from app.memory.factory import memory_store_factory

if TYPE_CHECKING:
    from app.memory.store import MemoryStore


# --------------------------------------------------------------------------
# spec 4: memory types
# --------------------------------------------------------------------------
class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"


@dataclass
class TaskRecord:
    """A persisted, durable record of one task execution (spec 61).

    Every field is stored in the MemoryStore under ``scope=TASK``, so a task
    is first-class memory: it can be queried, recalled, versioned, and synced
    across sessions and devices exactly like any other memory record.
    """

    task_id: str = ""
    content: str = ""
    summary: str = ""
    owner_id: str = "moon"
    agent_id: str = ""
    project_id: str = "MOON"
    scope: Scope = Scope.TASK
    task_status: TaskStatus = TaskStatus.PENDING
    result: str = ""
    exit_code: int | None = None
    start_time: float | None = None
    end_time: float | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    source_type: str = "AGENT"
    provenance: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.6
    importance: str = "MEDIUM"
    session_id: str = ""
    deleted: bool = False

    def mark_running(self) -> None:
        self.task_status = TaskStatus.RUNNING

    def mark_completed(self, result: str = "", *, exit_code: int = 0) -> None:
        self.task_status = TaskStatus.COMPLETED
        self.result = result
        self.exit_code = exit_code
        self.ended()

    def mark_failed(self, error: str = "") -> None:
        self.task_status = TaskStatus.FAILED
        self.result = error
        self.ended()

    def mark_cancelled(self) -> None:
        self.task_status = TaskStatus.CANCELLED
        self.ended()

    def mark_timed_out(self) -> None:
        self.task_status = TaskStatus.TIMED_OUT
        self.ended()

    def ended(self) -> None:
        self.end_time = time.time()
        self.updated_at = time.time()

    @classmethod
    def from_task(cls, task: "TaskRecord") -> "TaskRecord":  # noqa: F821
        """Reconstruct a :class:`TaskRecord` from a :class:`Task` model."""
        return cls(
            task_id=getattr(task, "id", ""),
            content=getattr(task, "prompt", ""),
            agent_id=getattr(task, "agent_name", ""),
            summary="",
            scope=Scope.TASK,
            task_status=TaskStatus.RUNNING,
            source_type="AGENT",
            session_id="",
            tags=[],
        )


# --------------------------------------------------------------------------
class TaskStore:
    """Durable, SQLite-backed task record store (spec 62).

    Wires the in-memory :class:`TaskRecord` to the persistent
    :class:`LocalMemoryStore` (SQLite). All task records land under
    ``scope=TASK`` / ``type=TASK`` with a stable upsert key
    ``project_id:task_id``, so they survive restarts and sync.

    Usage::

        store = TaskStore(memory_store_factory())
        store.record(task_record)     # upsert (idempotent)
        store.get(task_id)            # rehydrate
        store.list_tasks(status=PENDING)
        store.update(task_record)     # idempotent overwrite
        store.delete(task_id)         # soft-delete
    """

    def __init__(self, store: MemoryStore | None = None) -> None:
        self._store: MemoryStore = store or memory_store_factory()

    # -- public API ---------------------------------------------------------

    def record(self, task: TaskRecord) -> TaskRecord:
        """Persist (insert or update) a task record. Idempotent upsert."""
        self._store.record_task(task)
        return task

    def get(self, task_id: str, *, project_id: str = "MOON") -> TaskRecord | None:
        """Rehydrate a single task by id."""
        return self._store.get_task(task_id, project_id=project_id)

    def get_many(self, task_ids: list[str], *, project_id: str = "MOON") -> dict[str, TaskRecord]:
        """Rehydrate several tasks by id in one pass."""
        out: dict[str, TaskRecord] = {}
        for tid in task_ids:
            rec = self.get(tid, project_id=project_id)
            if rec is not None:
                out[tid] = rec
        return out

    def list_tasks(
        self,
        *,
        project_id: str = "MOON",
        status: TaskStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TaskRecord]:
        """List task records for a project, optionally filtered by status."""
        return self._store.list_tasks(project_id=project_id, status=status, limit=limit, offset=offset)

    def update(self, task: TaskRecord) -> TaskRecord:
        """Idempotent update of an existing task record."""
        return self._store.update_task(task)

    def delete(self, task_id: str, *, project_id: str = "MOON", hard: bool = False) -> bool:
        """Soft-delete a task record."""
        return self._store.delete_task(task_id, project_id=project_id, hard=hard)

    # -- introspection ------------------------------------------------------

    @property
    def store(self) -> "MemoryStore":  # noqa: F821
        return self._store

    def stats(self) -> dict[str, Any]:
        tasks = self.list_tasks(limit=100)
        by_status: dict[str, int] = {}
        for t in tasks:
            s = t.task_status.value
            by_status[s] = by_status.get(s, 0) + 1
        return {"total": len(tasks), "by_status": by_status}