"""Bounded subprocess execution for agent tools."""

from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Sequence
from dataclasses import dataclass

_CHUNK_SIZE = 64 * 1024
_CLEANUP_TIMEOUT = 2.0


@dataclass(frozen=True)
class ProcessCapture:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool


async def _read_limited(
    stream: asyncio.StreamReader, limit: int
) -> tuple[bytes, bool]:
    retained = bytearray()
    truncated = False
    while chunk := await stream.read(_CHUNK_SIZE):
        remaining = limit - len(retained)
        if remaining > 0:
            retained.extend(chunk[:remaining])
        if len(chunk) > remaining:
            truncated = True
    return bytes(retained), truncated


def _kill_process_tree(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None and os.name != "posix":
        return
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except ProcessLookupError:
        pass


async def run_bounded_process(
    command: str | Sequence[str],
    *,
    shell: bool = False,
    timeout: float,
    stdout_limit: int,
    stderr_limit: int,
) -> ProcessCapture:
    if shell:
        if not isinstance(command, str):
            raise TypeError("shell commands must be strings")
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=os.name == "posix",
        )
    else:
        if isinstance(command, str):
            raise TypeError("executable commands must be argument sequences")
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=os.name == "posix",
        )

    assert proc.stdout is not None
    assert proc.stderr is not None
    stdout_task = asyncio.create_task(_read_limited(proc.stdout, stdout_limit))
    stderr_task = asyncio.create_task(_read_limited(proc.stderr, stderr_limit))
    timed_out = False
    try:
        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            timed_out = True
            _kill_process_tree(proc)
            await asyncio.wait_for(proc.wait(), timeout=_CLEANUP_TIMEOUT)
        finally:
            _kill_process_tree(proc)
        stdout, stderr = await asyncio.wait_for(
            asyncio.gather(stdout_task, stderr_task),
            timeout=_CLEANUP_TIMEOUT,
        )
    except BaseException:
        _kill_process_tree(proc)
        for task in (stdout_task, stderr_task):
            task.cancel()
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        if proc.returncode is None:
            try:
                await asyncio.wait_for(proc.wait(), timeout=_CLEANUP_TIMEOUT)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        raise

    out, out_truncated = stdout
    err, err_truncated = stderr
    out_text = out.decode(errors="replace")
    err_text = err.decode(errors="replace")
    if out_truncated:
        out_text += "\n[stdout truncated]"
    if err_truncated:
        err_text += "\n[stderr truncated]"
    return ProcessCapture(
        returncode=proc.returncode if proc.returncode is not None else -1,
        stdout=out_text,
        stderr=err_text,
        timed_out=timed_out,
    )
