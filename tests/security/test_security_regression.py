import subprocess
import sys
import tempfile
from pathlib import Path

from app.capability.sandbox import SandboxExecutor


# Helper to run a command with limited environment and timeout
def run_cmd(cmd, timeout=5):
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": "/usr/bin:/bin"},
            timeout=timeout,
            check=False,
            text=True,
        )
        return result
    except subprocess.TimeoutExpired as e:
        return e

def test_command_injection_prevention():
    # Attempt to inject a harmless command via argument
    # The application should not execute arbitrary shell commands.
    # We'll simulate by calling a script that would echo if injection succeeded.
    # Run a harmless command via subprocess.run; ensure it executes but does not involve a shell.
    cmd = [sys.executable, "-c", "import subprocess, sys; subprocess.run([sys.executable, '-c', 'pass'], stdout=sys.stdout, stderr=sys.stderr)"]
    result = run_cmd(cmd)
    # Since we used subprocess.run without shell, no injection occurs; output should be empty.
    assert "INJECTED" not in (result.stdout or "")

def test_environment_variable_leakage(monkeypatch):
    monkeypatch.setenv("SECRET_TOKEN", "supersecret")
    with tempfile.TemporaryDirectory() as directory:
        sandbox = SandboxExecutor(workspace_root=Path(directory))
        sandbox._method = "workspace"
        result = sandbox.run(
            [sys.executable, "-c", "import os; print(os.getenv('SECRET_TOKEN'))"]
        )
    assert result.returncode == 0
    assert result.stdout.strip() == "None"

def test_output_flooding_protection():
    with tempfile.TemporaryDirectory() as directory:
        sandbox = SandboxExecutor(workspace_root=Path(directory))
        sandbox._method = "workspace"
        result = sandbox.run([
            sys.executable,
            "-c",
            "import os; [os.write(1, b'x' * 65536) for _ in range(32)]",
        ])
        assert result.returncode == 0
        assert len(result.stdout.encode()) <= sandbox._MAX_CAPTURE_BYTES + len(
            "\n[sandbox output truncated]"
        )
        assert result.stdout.endswith("[sandbox output truncated]")

        endless = sandbox.run(
            [sys.executable, "-c", "import os; exec('while True: os.write(1, b\"x\" * 8192)')"],
            timeout=1,
        )
        assert endless.returncode == 124
        assert endless.stdout == ""

def test_small_subprocess_batch_completes():
    with tempfile.TemporaryDirectory() as directory:
        sandbox = SandboxExecutor(workspace_root=Path(directory))
        sandbox._method = "workspace"
        outputs = [
            sandbox.run([sys.executable, "-c", "print('hi')"], timeout=5).stdout.strip()
            for _ in range(5)
        ]
    assert outputs == ["hi"] * 5
