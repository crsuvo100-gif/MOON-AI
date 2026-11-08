"""Database query tool (sqlite by default)."""

from __future__ import annotations

import logging
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)

_MAX_QUERY_CHARS = 10_000
_MAX_RESULT_CHARS = 20_000
_MAX_RESULT_ROWS = 50
_MAX_SQLITE_VALUE_BYTES = 64 * 1024
_MAX_SQLITE_COLUMNS = 64
_MAX_QUERY_SECONDS = 1.0
_MAX_VM_INSTRUCTIONS = 100_000


class DatabaseTool(BaseTool):
    name = "database"
    description = "Run a read-only SQL query against the local sqlite DB."

    async def execute(self, query: str = "", db: str = ":memory:", **kwargs: Any) -> str:
        if not query:
            return "[no query]"
        if len(query) > _MAX_QUERY_CHARS:
            return f"[db error: query exceeds {_MAX_QUERY_CHARS} characters]"
        if not re.match(r"^\s*select\b", query, flags=re.IGNORECASE):
            return "[only read queries allowed]"
        conn = None
        execution_limit_hit = False
        try:
            if db == ":memory:":
                conn = sqlite3.connect(":memory:")
            else:
                database_uri = f"{Path(db).resolve().as_uri()}?mode=ro"
                conn = sqlite3.connect(database_uri, uri=True)

            if hasattr(conn, "setlimit"):
                conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, _MAX_SQLITE_VALUE_BYTES)
                conn.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, _MAX_SQLITE_COLUMNS)

            allowed_actions = {
                sqlite3.SQLITE_SELECT,
                sqlite3.SQLITE_READ,
                sqlite3.SQLITE_FUNCTION,
                getattr(sqlite3, "SQLITE_RECURSIVE", -1),
            }

            def authorize(action, arg1, arg2, database, trigger):
                if action not in allowed_actions:
                    return sqlite3.SQLITE_DENY
                if action == sqlite3.SQLITE_FUNCTION and (arg2 or arg1 or "").lower() in {
                    "load_extension", "writefile", "readfile",
                }:
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK

            conn.set_authorizer(authorize)
            started = time.monotonic()
            instructions = 0
            execution_limit_hit = False

            def enforce_execution_budget() -> int:
                nonlocal instructions, execution_limit_hit
                instructions += 1_000
                if (
                    instructions > _MAX_VM_INSTRUCTIONS
                    or time.monotonic() - started > _MAX_QUERY_SECONDS
                ):
                    execution_limit_hit = True
                    return 1
                return 0

            conn.set_progress_handler(enforce_execution_budget, 1_000)
            cur = conn.execute(query)
            rows: list[str] = []
            result_size = 2
            truncated = False
            truncation_marker = ", [result truncated]"
            for _ in range(_MAX_RESULT_ROWS):
                row = cur.fetchone()
                if row is None:
                    break
                rendered = repr(row)
                separator = ", " if rows else ""
                if result_size + len(separator) + len(rendered) + len(truncation_marker) > _MAX_RESULT_CHARS:
                    truncated = True
                    break
                rows.append(separator + rendered)
                result_size += len(separator) + len(rendered)
            else:
                truncated = cur.fetchone() is not None

            result = "[" + "".join(rows)
            if truncated:
                result += truncation_marker
            return result + "]"
        except Exception as exc:  # noqa: BLE001
            if execution_limit_hit:
                return "[db error: query execution limit exceeded]"
            return f"[db error: {exc}]"
        finally:
            if conn is not None:
                conn.close()
