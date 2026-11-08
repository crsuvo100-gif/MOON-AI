"""Optional, permission-gated Agent Client Protocol subprocess connector."""

from __future__ import annotations

import asyncio
import json
import math
import os
import shutil
import signal
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

_MAX_MESSAGE_BYTES = 1_000_000
_MAX_ANSWER_BYTES = 1_000_000
_MAX_TASK_HISTORY = 1_000
_MAX_SESSION_ID_LENGTH = 4_096
_SAFE_ENV_KEYS = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE")


class ACPError(RuntimeError):
    """Raised when an ACP peer returns malformed or unsuccessful protocol data."""


@dataclass
class ACPTask:
    task_id: str
    status: str
    session_id: str = ""
    answer: str = ""
    stop_reason: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "session_id": self.session_id,
            "answer": self.answer,
            "stop_reason": self.stop_reason,
            "error": self.error,
        }


class ACPSubprocessConnector:
    """Talk to a local ACP agent over newline-delimited JSON-RPC stdio.

    The client advertises no filesystem or terminal capabilities and rejects
    permission requests because this connector has no interactive approval UI.
    ACP does not sandbox the agent process; callers must trust the executable.
    """

    def __init__(
        self,
        command: Sequence[str] | None = None,
        *,
        cwd: str | Path,
        timeout: float = 120.0,
        env: dict[str, str] | None = None,
    ) -> None:
        if command is None:
            hermes = shutil.which("hermes")
            command = (hermes or "hermes", "acp")
        if (
            isinstance(command, (str, bytes))
            or not command
            or not all(isinstance(part, str) and part for part in command)
        ):
            raise ValueError("ACP command must be a non-empty sequence of arguments")
        self._command = tuple(command)
        self._cwd = Path(cwd).resolve()
        if not self._cwd.is_dir():
            raise ValueError("ACP working directory must exist")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("ACP timeout must be a finite positive number")
        self._timeout = timeout
        self._env = {key: os.environ[key] for key in _SAFE_ENV_KEYS if key in os.environ}
        if env and not all(
            isinstance(key, str) and isinstance(value, str) for key, value in env.items()
        ):
            raise ValueError("ACP environment overrides must contain string keys and values")
        self._env.update(env or {})
        self._process: asyncio.subprocess.Process | None = None
        self._session_id = ""
        self._agent_info: dict[str, Any] = {}
        self._agent_capabilities: dict[str, Any] = {}
        self._next_id = 0
        self._answer_chunks: list[str] = []
        self._answer_bytes = 0
        self._answer_truncated = False
        self._tasks: dict[str, ACPTask] = {}
        self._lifecycle_lock = asyncio.Lock()
        self._request_lock = asyncio.Lock()
        self._stop_lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return (
            self._process is not None
            and self._process.returncode is None
            and bool(self._session_id)
        )

    @property
    def agent_info(self) -> dict[str, Any]:
        return dict(self._agent_info)

    @property
    def agent_capabilities(self) -> dict[str, Any]:
        return dict(self._agent_capabilities)

    async def connect(self) -> dict[str, Any]:
        async with self._lifecycle_lock:
            if self.connected:
                return {"ok": True, "session_id": self._session_id, "agent": self.agent_info}
            if self._process is not None:
                await self._stop_process()
            try:
                self._process = await asyncio.create_subprocess_exec(
                    *self._command,
                    cwd=self._cwd,
                    env=self._env,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    limit=_MAX_MESSAGE_BYTES,
                    start_new_session=(os.name == "posix"),
                )
                initialized = await self._request(
                    "initialize",
                    {
                        "protocolVersion": 1,
                        "clientCapabilities": {},
                        "clientInfo": {"name": "MOON", "version": "13.0"},
                    },
                )
                if not isinstance(initialized, dict) or initialized.get("protocolVersion") != 1:
                    raise ACPError("ACP agent did not negotiate protocol version 1")
                capabilities = initialized.get("agentCapabilities")
                if not isinstance(capabilities, dict):
                    raise ACPError("ACP initialize response is missing agent capabilities")
                agent_info = initialized.get("agentInfo")
                if agent_info is not None and not isinstance(agent_info, dict):
                    raise ACPError("ACP initialize response has invalid agentInfo")
                if isinstance(agent_info, dict):
                    for field in ("name", "version"):
                        value = agent_info.get(field)
                        if value is not None and (
                            not isinstance(value, str) or not value.strip()
                        ):
                            raise ACPError(f"ACP agentInfo has invalid {field}")
                    self._agent_info = agent_info
                else:
                    self._agent_info = {}
                self._agent_capabilities = capabilities
                session = await self._request(
                    "session/new",
                    {"cwd": str(self._cwd), "mcpServers": []},
                )
                session_id = session.get("sessionId") if isinstance(session, dict) else None
                if (
                    not isinstance(session_id, str)
                    or not session_id
                    or len(session_id) > _MAX_SESSION_ID_LENGTH
                ):
                    raise ACPError("ACP session/new response is missing sessionId")
                self._session_id = session_id
                return {
                    "ok": True,
                    "session_id": session_id,
                    "agent": self.agent_info,
                    "capabilities": self.agent_capabilities,
                }
            except Exception:
                await self._stop_process()
                raise

    async def delegate(self, objective: str, *, confirmed: bool = False) -> dict[str, Any]:
        task = ACPTask(task_id=str(uuid.uuid4()), status="pending")
        if len(self._tasks) >= _MAX_TASK_HISTORY:
            del self._tasks[next(iter(self._tasks))]
        self._tasks[task.task_id] = task
        if confirmed is not True:
            task.status = "blocked"
            task.error = "explicit confirmation required before delegating to an ACP agent"
            return task.to_dict()
        if not isinstance(objective, str) or not objective.strip():
            task.status = "failed"
            task.error = "objective must be a non-empty string"
            return task.to_dict()
        try:
            objective_size = len(json.dumps(objective, separators=(",", ":")).encode("utf-8"))
        except UnicodeEncodeError:
            task.status = "failed"
            task.error = "objective contains invalid Unicode"
            return task.to_dict()
        if objective_size > _MAX_MESSAGE_BYTES - _MAX_SESSION_ID_LENGTH - 1024:
            task.status = "failed"
            task.error = "objective exceeds ACP message size limit"
            return task.to_dict()

        async with self._request_lock:
            try:
                if not self.connected:
                    await self.connect()
                task.status = "running"
                task.session_id = self._session_id
                self._answer_chunks.clear()
                self._answer_bytes = 0
                self._answer_truncated = False
                response = await self._request(
                    "session/prompt",
                    {
                        "sessionId": self._session_id,
                        "prompt": [{"type": "text", "text": objective}],
                    },
                )
                stop_reason = response.get("stopReason") if isinstance(response, dict) else None
                if not isinstance(stop_reason, str) or not stop_reason:
                    raise ACPError("ACP session/prompt response is missing stopReason")
                task.stop_reason = stop_reason
                task.answer = self._extract_answer()
                if stop_reason == "cancelled":
                    task.status = "cancelled"
                    return task.to_dict()
                if not task.answer.strip():
                    raise ACPError("ACP agent completed without a text response")
                task.status = "completed"
                return task.to_dict()
            except Exception as exc:
                task.status = "failed"
                task.error = str(exc)
                await self._stop_process()
                return task.to_dict()

    def get_task(self, task_id: str) -> dict[str, str] | None:
        task = self._tasks.get(task_id)
        return task.to_dict() if task else None

    async def close(self) -> None:
        async with self._lifecycle_lock:
            await self._stop_process()

    async def _request(self, method: str, params: dict[str, Any]) -> Any:
        process = self._process
        if process is None or process.returncode is not None or not process.stdin or not process.stdout:
            raise ACPError("ACP agent process is not running")
        self._next_id += 1
        request_id = self._next_id
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        request_line = json.dumps(
            payload, separators=(",", ":"), allow_nan=False
        ).encode() + b"\n"
        if len(request_line) > _MAX_MESSAGE_BYTES:
            raise ACPError(f"ACP request {method} exceeds message size limit")
        process.stdin.write(request_line)
        await process.stdin.drain()
        deadline = asyncio.get_running_loop().time() + self._timeout

        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise ACPError(f"ACP request {method} timed out")
            try:
                line = await asyncio.wait_for(process.stdout.readline(), timeout=remaining)
            except (asyncio.TimeoutError, ValueError, asyncio.LimitOverrunError) as exc:
                raise ACPError(f"ACP request {method} timed out or exceeded message limits") from exc
            if not line:
                raise ACPError("ACP agent closed its output stream")
            if len(line) > _MAX_MESSAGE_BYTES:
                raise ACPError("ACP agent message exceeds size limit")
            try:
                message = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ACPError("ACP agent emitted invalid JSON-RPC") from exc
            if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                raise ACPError("ACP agent emitted an invalid JSON-RPC envelope")
            if message.get("method") == "session/update":
                params_obj = message.get("params")
                if isinstance(params_obj, dict):
                    self._record_update(params_obj)
                continue
            if "method" in message:
                await self._answer_agent_request(message)
                continue
            if message.get("id") != request_id:
                continue
            if "error" in message:
                error = message["error"]
                detail = error.get("message", "unknown ACP error") if isinstance(error, dict) else str(error)
                raise ACPError(f"ACP {method} failed: {detail}")
            if "result" not in message:
                raise ACPError(f"ACP {method} response is missing result")
            return message["result"]

    async def _answer_agent_request(self, message: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None:
            return
        request_id = message.get("id")
        if request_id is None:
            return
        if message.get("method") == "session/request_permission":
            params = message.get("params")
            options = params.get("options", []) if isinstance(params, dict) else []
            reject = next(
                (
                    option.get("optionId")
                    for option in options
                    if isinstance(option, dict) and option.get("kind") == "reject_once"
                ),
                None,
            )
            outcome = (
                {"outcome": "selected", "optionId": reject}
                if isinstance(reject, str)
                else {"outcome": "cancelled"}
            )
            response = {"outcome": outcome}
        else:
            response = None
        envelope: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
        if response is not None:
            envelope["result"] = response
        else:
            envelope["error"] = {"code": -32601, "message": "client method is not supported"}
        process.stdin.write(json.dumps(envelope, separators=(",", ":")).encode() + b"\n")
        await process.stdin.drain()

    def _record_update(self, params: dict[str, Any]) -> None:
        if params.get("sessionId") != self._session_id:
            return
        update = params.get("update")
        if not isinstance(update, dict) or update.get("sessionUpdate") != "agent_message_chunk":
            return
        content = update.get("content")
        if not isinstance(content, dict) or content.get("type") != "text":
            return
        text = content.get("text")
        if not isinstance(text, str):
            return
        encoded = text.encode("utf-8")
        available = _MAX_ANSWER_BYTES - self._answer_bytes
        if available <= 0:
            self._answer_truncated = True
            return
        if len(encoded) > available:
            text = encoded[:available].decode("utf-8", errors="ignore")
            self._answer_truncated = True
        self._answer_chunks.append(text)
        self._answer_bytes += len(text.encode("utf-8"))

    def _extract_answer(self) -> str:
        answer = "".join(self._answer_chunks)
        if self._answer_truncated:
            answer += "\n[ACP response truncated]"
        return answer

    async def _stop_process(self) -> None:
        async with self._stop_lock:
            process = self._process
            self._process = None
            self._session_id = ""
            self._agent_info = {}
            self._agent_capabilities = {}
            if process is None or process.returncode is not None:
                return
            if process.stdin:
                process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                if os.name == "posix":
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                else:
                    process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    if os.name == "posix":
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    else:
                        process.kill()
                    await process.wait()
