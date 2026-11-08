import json
import sys

import app.connector.acp as acp_module
import main
import moon.__main__ as moon_cli


def test_acp_cli_requires_confirmation_before_starting_agent(monkeypatch, tmp_path, capsys):
    class UnexpectedConnector:
        def __init__(self, **kwargs):
            raise AssertionError("unconfirmed delegation must not start an agent")

    monkeypatch.setattr(acp_module, "ACPSubprocessConnector", UnexpectedConnector)

    result = main._cmd_acp("inspect project", tmp_path, confirmed=False)

    assert result == 2
    assert "--confirm" in capsys.readouterr().err


def test_acp_cli_delegates_only_after_confirmation(monkeypatch, tmp_path, capsys):
    seen = {}

    class FakeConnector:
        def __init__(self, *, cwd):
            seen["cwd"] = cwd

        async def delegate(self, objective, *, confirmed=False):
            seen["objective"] = objective
            seen["confirmed"] = confirmed
            return {"status": "completed", "answer": "done"}

        async def close(self):
            seen["closed"] = True

    monkeypatch.setattr(acp_module, "ACPSubprocessConnector", FakeConnector)

    result = main._cmd_acp("inspect project", tmp_path, confirmed=True)

    assert result == 0
    assert capsys.readouterr().out.strip() == "done"
    assert seen == {
        "cwd": tmp_path,
        "objective": "inspect project",
        "confirmed": True,
        "closed": True,
    }


def test_acp_cli_inspects_declared_agent_manifest(monkeypatch, tmp_path, capsys):
    seen = {}
    manifest = {
        "ok": True,
        "session_id": "test-session",
        "agent": {"name": "fake-acp", "version": "1"},
        "capabilities": {"prompt": True},
    }

    class FakeConnector:
        def __init__(self, *, cwd):
            seen["cwd"] = cwd

        async def connect(self):
            seen["connected"] = True
            return manifest

        async def delegate(self, *args, **kwargs):
            raise AssertionError("inspection must not delegate a task")

        async def close(self):
            seen["closed"] = True

    monkeypatch.setattr(acp_module, "ACPSubprocessConnector", FakeConnector)

    result = main._cmd_acp("", tmp_path, confirmed=True, inspect_only=True)

    assert result == 0
    assert json.loads(capsys.readouterr().out) == manifest
    assert seen == {"cwd": tmp_path, "connected": True, "closed": True}


def test_acp_cli_parsers_require_explicit_confirmation_flag(monkeypatch, tmp_path):
    main_args = [
        "moon",
        "acp",
        "inspect",
        "project",
        "--workspace",
        str(tmp_path),
        "--confirm",
    ]
    monkeypatch.setattr(sys, "argv", main_args)
    monkeypatch.setattr(main, "_ensure_default_peer", lambda: None)
    forwarded = {}
    monkeypatch.setattr(
        main,
        "_cmd_acp",
        lambda objective, workspace, *, confirmed, inspect_only: forwarded.update(
            objective=objective,
            workspace=workspace,
            confirmed=confirmed,
            inspect_only=inspect_only,
        ) or 0,
    )

    assert main.main() == 0
    assert forwarded == {
        "objective": "inspect project",
        "workspace": str(tmp_path),
        "confirmed": True,
        "inspect_only": False,
    }

    parsed = moon_cli._build_parser().parse_args(
        [
            "acp",
            "--inspect",
            "--workspace",
            str(tmp_path),
            "--confirm",
        ]
    )
    assert parsed.confirm is True
    assert parsed.inspect is True
    assert parsed.objective == []
