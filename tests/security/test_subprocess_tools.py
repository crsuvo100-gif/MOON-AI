import sys

import pytest

from app.tools.process_capture import run_bounded_process
from app.tools.python_executor import PythonExecutorTool


@pytest.mark.asyncio
async def test_python_executor_bounds_code_and_output():
    tool = PythonExecutorTool()
    oversized = await tool.execute("x" * 100_001)
    assert "code exceeds" in oversized

    output = await tool.execute(
        "import sys; sys.stdout.write('o' * 1000000); "
        "sys.stderr.write('e' * 1000000)"
    )
    assert len(output) < 3_000
    assert "[stdout truncated]" in output
    assert "[stderr truncated]" in output


@pytest.mark.asyncio
async def test_bounded_process_runner_terminates_timed_out_child():
    result = await run_bounded_process(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        timeout=0.1,
        stdout_limit=100,
        stderr_limit=100,
    )
    assert result.timed_out
    assert result.returncode != 0

