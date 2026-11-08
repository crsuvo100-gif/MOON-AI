from app.memory import task_ledger
from app.memory.task_record import TaskRecord, TaskStore


class _MemoryStore:
    def record_task(self, task):
        pass


class _FailingLedger:
    def record(self, task):
        raise OSError("ledger unavailable")


def test_record_keeps_ledger_write_best_effort(monkeypatch, caplog):
    monkeypatch.setattr(task_ledger, "get_ledger", lambda: _FailingLedger())

    record = TaskRecord(task_id="task-1")
    result = TaskStore(store=_MemoryStore()).record(record)

    assert result is record
    assert "local task ledger write failed" in caplog.text
