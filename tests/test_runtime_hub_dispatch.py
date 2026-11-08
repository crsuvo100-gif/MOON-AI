from __future__ import annotations

import sys

import pytest

import main
from app.brain.orchestrator import Orchestrator
from app.brain.tool_manager import ToolManager
from app.connector.hub import IntegrationHub
from app.models.task import Task
from app.tools.registry import ToolRegistry
from app.tools.utility_tools import UnitConverterTool


def test_work_without_task_prints_usage(monkeypatch, capsys):
    monkeypatch.setattr(main, "_ensure_default_peer", lambda: None)
    monkeypatch.setattr(sys, "argv", ["moon", "work"])

    assert main.main() == 1
    assert "usage: moon work <task>" in capsys.readouterr().err


def test_work_prints_the_orchestrator_result(monkeypatch, capsys):
    class FakeHub:
        def __init__(self):
            pass

        async def execute_permitted_task(self, task, *, confirmed=False):
            assert task == "a harmless test task"
            assert confirmed is False
            return {"ok": True, "result": "MOON_RESULT"}

    monkeypatch.setattr(main, "_ensure_default_peer", lambda: None)
    monkeypatch.setattr(sys, "argv", ["moon", "work", "a harmless test task"])
    monkeypatch.setattr("app.connector.hub.IntegrationHub", FakeHub)

    assert main.main() == 0
    assert "MOON_RESULT" in capsys.readouterr().out


def test_work_confirmation_flag_reaches_hub(monkeypatch):
    class FakeHub:
        def __init__(self):
            pass

        async def execute_permitted_task(self, task, *, confirmed=False):
            assert task == "a harmless test task"
            assert confirmed is True
            return {"ok": True, "result": "confirmed"}

    monkeypatch.setattr(main, "_ensure_default_peer", lambda: None)
    monkeypatch.setattr(
        sys, "argv", ["moon", "work", "a harmless test task", "--confirmed"]
    )
    monkeypatch.setattr("app.connector.hub.IntegrationHub", FakeHub)

    assert main.main() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "text", "expected_ok", "confirmed"),
    [
        ("completed", "safe result", True, False),
        ("failed", "provider unavailable", False, False),
        ("completed", "", False, False),
        ("completed", "safe result", True, True),
    ],
)
async def test_integration_hub_uses_brain_and_reports_real_status(
    monkeypatch, status, text, expected_ok, confirmed
):
    calls = []

    class FakeOrchestrator:
        def __init__(self, _settings):
            pass

        async def setup(self):
            calls.append("setup")

        async def run_task(self, task):
            assert isinstance(task, Task)
            assert task.prompt == "a harmless test task"
            assert task.agent_name == "auto"
            assert task.data.get("confirmed_connection") == (
                "moon_local" if confirmed else None
            )
            task.status = status
            task.result = text
            return task

        async def teardown(self):
            calls.append("teardown")

    monkeypatch.setattr("app.brain.orchestrator.Orchestrator", FakeOrchestrator)
    monkeypatch.setattr("app.config.settings.get_settings", lambda: object())

    result = await IntegrationHub.execute_permitted_task(
        object(), "a harmless test task", confirmed=confirmed
    )

    assert result["ok"] is expected_ok
    assert result["executed_via"] == "moon_brain_orchestrator"
    assert result["status"] == status
    assert calls == ["setup", "teardown"]


@pytest.mark.asyncio
async def test_integration_hub_tears_down_after_setup_failure(monkeypatch):
    calls = []

    class FakeOrchestrator:
        def __init__(self, _settings):
            pass

        async def setup(self):
            calls.append("setup")
            raise RuntimeError("model unavailable")

        async def teardown(self):
            calls.append("teardown")

    monkeypatch.setattr("app.brain.orchestrator.Orchestrator", FakeOrchestrator)
    monkeypatch.setattr("app.config.settings.get_settings", lambda: object())

    result = await IntegrationHub.execute_permitted_task(
        object(), "a harmless test task"
    )

    assert result == {"ok": False, "error": "orchestrator setup failed: model unavailable"}
    assert calls == ["setup", "teardown"]


@pytest.mark.asyncio
async def test_orchestrator_executes_explicit_unit_converter_request():
    registry = ToolRegistry()
    registry.register(UnitConverterTool())
    orchestrator = object.__new__(Orchestrator)
    orchestrator._tools = ToolManager(registry)

    result = await orchestrator._try_explicit_tool(
        Task(prompt="Use unit_converter to convert 10 m to ft."),
        "",
        type("Agent", (), {"name": "test-agent"})(),
    )

    assert result is not None
    assert "10.0 m = 32.8084 ft" in result[1]


@pytest.mark.parametrize(
    ("tool_name", "connection_name", "confirmed", "expected"),
    [
        ("global_connector", "moon_local", "moon_local", True),
        ("global_connector", "other_peer", "moon_local", False),
        ("global_connector", "moon_local", None, False),
        ("api_requests", "moon_local", "moon_local", False),
    ],
)
def test_task_confirmation_is_limited_to_moon_local_connector(
    tool_name, connection_name, confirmed, expected
):
    task = Task(
        prompt="test",
        data={"confirmed_connection": confirmed} if confirmed else {},
    )
    args = {"name": connection_name}

    Orchestrator._apply_task_confirmation(task, tool_name, args)

    assert args.get("confirmed", False) is expected
