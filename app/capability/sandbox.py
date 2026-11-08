"""SandboxExecutor -- run installs/tests with isolation best-effort.

Uses the best available isolation runtime without forcing Docker. Tries, in
order: bubblewrap (bwrap) -> podman -> docker -> workspace fallback. The
fallback sanitizes environment variables, limits captured output, and applies
a timeout, but does not isolate filesystem access or disable networking.
"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SandboxResult:
    returncode: int
    stdout: str
    stderr: str
    method: str


class SandboxExecutor:
    _MAX_CAPTURE_BYTES = 1_000_000
    _SAFE_ENV_KEYS = (
        "PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE",
        "TMPDIR", "TMP", "TEMP", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT",
    )

    def __init__(self, workspace_root: str | Path | None = None) -> None:
        self.workspace = Path(workspace_root or Path.cwd()).resolve()
        self._method = self._detect()

    def _detect(self) -> str:
        if shutil.which("bwrap"):
            return "bubblewrap"
        if shutil.which("podman"):
            return "podman"
        if shutil.which("docker"):
            return "docker"
        return "workspace"

    @property
    def method(self) -> str:
        return self._method

    def run(self, cmd: list[str], *, timeout: int = 180, network: bool = False,
            cwd: str | Path | None = None) -> SandboxResult:
        cwd_path = Path(cwd or self.workspace).resolve()
        env = {key: os.environ[key] for key in self._SAFE_ENV_KEYS if key in os.environ}
        if self._method == "bubblewrap":
            return self._run_bwrap(cmd, timeout, network, cwd_path, env)
        if self._method == "podman":
            return self._run_podman(cmd, timeout, network, cwd_path, env)
        if self._method == "docker":
            return self._run_docker(cmd, timeout, network, cwd_path, env)
        return self._run_workspace(cmd, timeout, network, cwd_path, env)

    # ------------------------------------------------------------------
    def _run_bwrap(self, cmd, timeout, network, cwd, env) -> SandboxResult:
        bcmd = [
            "bwrap",
            "--ro-bind", "/", "/",
            "--bind", str(cwd), str(cwd),
            "--dev", "/dev", "--proc", "/proc",
            "--unshare-pid",
        ]
        if not network:
            bcmd.append("--unshare-net")
        bcmd += ["--chdir", str(cwd), "--"]
        bcmd += cmd
        return self._exec(bcmd, timeout, cwd, env)

    def _run_podman(self, cmd, timeout, network, cwd, env) -> SandboxResult:
        pcmd = ["podman", "run", "--rm", "-v", f"{cwd}:/work:Z", "-w", "/work"]
        if not network:
            pcmd.append("--network=none")
        pcmd += ["python:3.11-slim", *cmd]
        return self._exec(pcmd, timeout, cwd, env)

    def _run_docker(self, cmd, timeout, network, cwd, env) -> SandboxResult:
        dcmd = ["docker", "run", "--rm", "-v", f"{cwd}:/work", "-w", "/work"]
        if not network:
            dcmd.append("--network=none")
        dcmd += ["python:3.11-slim", *cmd]
        return self._exec(dcmd, timeout, cwd, env)

    def _run_workspace(self, cmd, timeout, network, cwd, env) -> SandboxResult:
        # This fallback only sanitizes the environment and bounds execution/output;
        # it does not provide filesystem, resource, or network isolation.
        if not network:
            logger.warning("sandbox workspace fallback cannot disable network access")
        return self._exec(cmd, timeout, cwd, env)

    def _exec(self, cmd, timeout, cwd, env) -> SandboxResult:
        captured: dict[str, bytearray] = {
            "stdout": bytearray(),
            "stderr": bytearray(),
        }
        truncated = {"stdout": False, "stderr": False}

        def drain(stream, name: str) -> None:
            try:
                while True:
                    chunk = stream.read(8192)
                    if not chunk:
                        return
                    available = self._MAX_CAPTURE_BYTES - len(captured[name])
                    if available > 0:
                        captured[name].extend(chunk[:available])
                    if len(chunk) > available:
                        truncated[name] = True
            except (OSError, ValueError):
                return

        try:
            process = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                start_new_session=(os.name == "posix"),
            )
            readers = [
                threading.Thread(target=drain, args=(process.stdout, "stdout"), daemon=True),
                threading.Thread(target=drain, args=(process.stderr, "stderr"), daemon=True),
            ]
            for reader in readers:
                reader.start()
            try:
                returncode = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                else:
                    process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    if os.name == "posix":
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    else:
                        process.kill()
                    process.wait()
                for reader in readers:
                    reader.join(timeout=2)
                return SandboxResult(124, "", "sandbox: command timed out", self._method)
            finally:
                if process.stdout:
                    process.stdout.close()
                if process.stderr:
                    process.stderr.close()
            for reader in readers:
                reader.join()

            def output(name: str) -> str:
                value = bytes(captured[name]).decode("utf-8", errors="replace")
                if truncated[name]:
                    value += "\n[sandbox output truncated]"
                return value

            return SandboxResult(returncode, output("stdout"), output("stderr"), self._method)
        except Exception as exc:  # noqa: BLE001
            logger.warning("sandbox command failed: %s", exc)
            return SandboxResult(1, "", f"sandbox error: {exc}", self._method)

    # ------------------------------------------------------------------
    # Optional install helpers; the workspace fallback must never run installers.
    # ------------------------------------------------------------------
    def install(self, spec: dict) -> SandboxResult:
        """Install a capability spec inside the sandbox."""
        if self._method == "workspace":
            return self._workspace_install_error()
        method = spec.get("method", "pip")
        pkg = spec.get("package", "")
        if method == "pip":
            return self.run(["pip", "install", pkg], timeout=300)
        if method == "system":
            return self.run(["apt-get", "install", "-y", pkg], timeout=300)
        return SandboxResult(1, "", f"unsupported install method: {method}", self._method)

    def install_pip(self, pkg: str) -> SandboxResult:
        """Install a pip package inside the sandbox."""
        if self._method == "workspace":
            return self._workspace_install_error()
        return self.run(["pip", "install", pkg], timeout=300)

    def _workspace_install_error(self) -> SandboxResult:
        message = (
            "sandboxed installation unavailable: install requires bubblewrap, "
            "podman, or docker; workspace fallback is not an isolation boundary"
        )
        return SandboxResult(1, "", message, self._method)
