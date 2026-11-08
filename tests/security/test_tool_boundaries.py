import sqlite3
from unittest.mock import patch

import pytest

from app.security.authorization import require_auth
from app.tools.database import DatabaseTool
from app.tools.file_manager import FileManagerTool


def test_private_addresses_are_not_implicitly_authorized(monkeypatch):
    monkeypatch.delenv("AUTHORIZED_TARGETS", raising=False)
    assert not require_auth("10.0.0.5").allowed
    assert not require_auth("127.0.0.1").allowed
    assert not require_auth("10.0.0.5", confirmed="true").allowed


def test_authorized_targets_support_explicit_cidrs(monkeypatch):
    monkeypatch.setenv("AUTHORIZED_TARGETS", "10.0.0.0/8,example.test")
    assert require_auth("10.2.3.4").allowed
    assert require_auth("EXAMPLE.TEST.").allowed
    assert not require_auth("192.168.1.1").allowed


@pytest.mark.asyncio
async def test_database_tool_only_reads_existing_database(tmp_path):
    database = tmp_path / "records.sqlite"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE records (value TEXT)")
        conn.execute("INSERT INTO records VALUES ('preserved')")

    tool = DatabaseTool()
    result = await tool.execute("SELECT value FROM records", db=str(database))
    assert "preserved" in result
    assert "[only read queries allowed]" in await tool.execute(
        "PRAGMA query_only=OFF", db=str(database)
    )
    assert "[only read queries allowed]" in await tool.execute(
        "UPDATE records SET value='changed'", db=str(database)
    )
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT value FROM records").fetchone()[0] == "preserved"


@pytest.mark.asyncio
async def test_database_tool_bounds_query_size_and_result_output():
    tool = DatabaseTool()
    oversized = await tool.execute("SELECT 1 " + " " * 10_000)
    assert "query exceeds" in oversized

    large_result = await tool.execute(
        "SELECT printf('%01000d', value) FROM (WITH RECURSIVE valueset(value) AS ("
        "SELECT 1 UNION ALL SELECT value + 1 FROM valueset WHERE value < 50"
        ") SELECT value FROM valueset)"
    )
    assert len(large_result) <= 20_000
    assert "result truncated" in large_result


@pytest.mark.asyncio
async def test_database_tool_interrupts_excessive_sqlite_work():
    result = await DatabaseTool().execute(
        "SELECT sum(value) FROM (WITH RECURSIVE valueset(value) AS ("
        "SELECT 1 UNION ALL SELECT value + 1 FROM valueset "
        "WHERE value < 100000000"
        ") SELECT value FROM valueset)"
    )
    assert result == "[db error: query execution limit exceeded]"


@pytest.mark.asyncio
async def test_file_manager_requires_explicit_overwrite_and_stays_in_root(tmp_path):
    original = tmp_path / "notes.txt"
    original.write_text("original", encoding="utf-8")
    tool = FileManagerTool(allowed_root=str(tmp_path))

    refused = await tool.execute(action="write", path="notes.txt", content="replacement")
    assert "error" in refused
    assert original.read_text(encoding="utf-8") == "original"

    written = await tool.execute(
        action="write", path="notes.txt", content="replacement", overwrite=True
    )
    assert "wrote" in written
    assert original.read_text(encoding="utf-8") == "replacement"
    assert tool.is_dangerous()

    escaped = await tool.execute(action="write", path="../outside.txt", content="bad")
    assert "error" in escaped
    assert not (tmp_path.parent / "outside.txt").exists()


@pytest.mark.asyncio
async def test_file_manager_atomic_overwrite_preserves_original_on_replace_failure(tmp_path):
    target = tmp_path / "notes.txt"
    target.write_text("original", encoding="utf-8")
    tool = FileManagerTool(allowed_root=str(tmp_path))

    with patch("app.tools.file_manager.os.replace", side_effect=OSError("replace failed")):
        result = await tool.execute(
            action="write", path="notes.txt", content="replacement", overwrite=True
        )

    assert "replace failed" in result
    assert target.read_text(encoding="utf-8") == "original"
    assert not list(tmp_path.glob(".notes.txt.*.tmp"))


@pytest.mark.asyncio
async def test_file_manager_bounds_reads_and_writes(tmp_path):
    target = tmp_path / "large.txt"
    target.write_text("x" * 10_000, encoding="utf-8")
    tool = FileManagerTool(allowed_root=str(tmp_path))

    assert len(await tool.execute(action="read", path="large.txt")) == 4_000
    refused = await tool.execute(action="write", path="too-large.txt", content="x" * 1_000_001)
    assert "content exceeds" in refused
    assert not (tmp_path / "too-large.txt").exists()
