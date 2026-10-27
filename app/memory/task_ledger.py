"""task_ledger.py -- local task ledger (spec 61/62/63 extended).

Durable, source-folder-backed task ledger.  Every task the agent completes is
persisted here as an append-only JSON file inside the MOON source folder, so
task completions are *physically present* on disk in the project -- not only
in the SQLite memory database.

Two save targets are deliberately separated (spec 88):

    * SQLite : ~/.moon/memory/main.sqlite          -- the canonical memory DB
    * local  : <project>/tasks/<task_id>.json      -- PROJECT SOURCE FOLDER save

This module owns the *local* save: the canonical memory DB stays write-led,
the local ledger stays readable offline and git-able.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.memory.task_record import TaskRecord, TaskStatus

# Canonical project root (MOON source folder).  All local task JSONs land here.
_DEFAULT_PROJECT_ROOT = Path("/home/meow/Projects/MOON")

# Local ledger index file (in-project JSON, human/grep-able).
_LEGER_INDEX = "tasks/ledger.json"
# Per-task snapshot files.
_TASK_DIR = "tasks"


class LocalTaskLedger:
    """Append-only local task ledger written into the project source folder."""

    def __init__(self, project_root: Path | None = None) -> None:
        self._project_root = Path(project_root) if project_root else _DEFAULT_PROJECT_ROOT
        self._project_root.mkdir(parents=True, exist_ok=True)
        self._task_dir = self._project_root / _TASK_DIR
        self._task_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._project_root / _LEGER_INDEX
        self._index: dict[str, Any] = {"version": 1, "entries": {}}
        self._load()

    # -- properties ----------------------------------------------------------

    @property
    def project_root(self) -> Path:
        """The source-folder location where local task JSONs are written."""
        return self._project_root

    # -- persistence ---------------------------------------------------------

    def _load(self) -> None:
        if self._index_path.exists():
            try:
                self._index = json.loads(self._index_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._index = {"version": 1, "entries": {}}

    def _save(self) -> None:
        tmp = self._index_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._index, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._index_path)  # atomic replace on POSIX

    def _entry_file(self, task_id: str) -> Path:
        safe = task_id.replace(":", "_").replace("/", "_")
        return self._task_dir / f"{safe}.json"

    # -- public API ----------------------------------------------------------

    def record(self, task: TaskRecord) -> Path:
        """Persist a completed task snapshot into the source folder.

        Called on every task lifecycle event; overwrites are idempotent so a
        re-run of the same task_id yields the current snapshot.
        """
        now = time.time()
        entry = {
            "task_id": task.task_id,
            "content": task.content,
            "summary": task.summary,
            "owner_id": task.owner_id,
            "agent_id": task.agent_id,
            "project_id": task.project_id,
            "scope": task.scope.value,
            "task_status": task.task_status.value,
            "result": task.result,
            "exit_code": task.exit_code,
            "start_time": task.start_time,
            "end_time": task.end_time,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "tags": task.tags,
            "metadata": task.metadata,
            "source_type": task.source_type,
            "provenance": task.provenance,
            "confidence": task.confidence,
            "importance": task.importance,
            "session_id": task.session_id,
            "deleted": task.deleted,
            "recorded_at": datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        }
        # Persist the JSON snapshot.
        entry_path = self._entry_file(task.task_id)
        entry_path.write_text(json.dumps(entry, indent=2, ensure_ascii=False), encoding="utf-8")

        # Update the index.
        self._index.setdefault("entries", {})
        self._index["entries"][task.task_id] = {
            "file": f"tasks/{task.task_id.replace(':', '_').replace('/', '_')}.json",
            "status": task.task_status.value,
            "recorded_at": entry["recorded_at"],
        }
        self._save()
        return entry_path

    def get(self, task_id: str) -> dict[str, Any] | None:
        """Rehydrate one task snapshot from the source folder."""
        path = self._entry_file(task_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def list_entries(self, status: str | None = None) -> list[dict[str, Any]]:
        """Return all ledger index entries, optionally filtered by status."""
        out = []
        for tid, meta in self._index.get("entries", {}).items():
            if status is None or meta.get("status") == status:
                out.append({"task_id": tid, **meta})
        out.sort(key=lambda e: e.get("recorded_at", ""), reverse=True)
        return out

    def entry_count(self) -> int:
        return len(self._index.get("entries", {}))


# Convenience singleton used across the project.
_default_ledger: LocalTaskLedger | None = None


def get_ledger(project_root: Path | None = None) -> LocalTaskLedger:
    global _default_ledger
    if _default_ledger is None or project_root != _default_ledger.project_root:
        _default_ledger = LocalTaskLedger(project_root)
    return _default_ledger


__all__ = ["LocalTaskLedger", "get_ledger"]
