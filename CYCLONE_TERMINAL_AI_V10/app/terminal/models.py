from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class ExecutionRequest(BaseModel):
    command: str = Field(..., description="Raw command string to execute")
    cwd: Path | None = Field(None, description="Working directory; defaults to session cwd")
    env: Mapping[str, str] | None = Field(None, description="Extra environment variables for the command")
    backend: Literal["local", "docker", "ssh"] = Field("local", description="Backend to run the command on")
    shell: bool = Field(False, description="Run via /bin/sh – enables pipelines, redirects, etc.")
    timeout: int | None = Field(60, description="Maximum seconds before the command is killed")
    background: bool = Field(False, description="If true, run asynchronously and return execution_id immediately")
    interactive: bool = Field(False, description="Require PTY (interactive terminal) support")
    permission_mode: Literal["auto", "ask", "deny"] = Field("ask", description="Permission handling for risky commands")
    verification: dict | None = Field(None, description="Verification spec – e.g. {\"type\": \"file_exists\", \"path\": \"/tmp/out\"}")

class ExecutionResult(BaseModel):
    execution_id: str = Field(..., description="Unique ID for this execution instance")
    command: str = Field(..., description="Command that was executed")
    backend: str = Field(..., description="Backend used (local, docker, ssh)")
    cwd: Path = Field(..., description="Working directory at execution time")
    status: Literal["success", "failed", "cancelled", "timed_out", "denied"] = Field(..., description="Final status of the execution")
    exit_code: int | None = Field(None, description="Process exit code when applicable")
    stdout: str | None = Field(None, description="Captured standard output (truncated if very large)")
    stderr: str | None = Field(None, description="Captured standard error (truncated if very large)")
    pid: int | None = Field(None, description="PID of the process (if available)")
    duration: float = Field(..., description="Runtime in seconds")
    verified: bool = Field(False, description="Whether post‑execution verification succeeded")
    verification_result: dict | None = Field(None, description="Result payload from verification engine")
    error: str | None = Field(None, description="Human‑readable error message if status != success")
