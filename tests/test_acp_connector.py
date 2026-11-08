import sys

import pytest

from app.connector.acp import (
    _MAX_ANSWER_BYTES,
    _MAX_MESSAGE_BYTES,
    _MAX_TASK_HISTORY,
    ACPError,
    ACPSubprocessConnector,
)

_FAKE_AGENT = r"""
import json
import os
import sys

def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()

for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if method == "initialize":
        assert request["params"]["clientCapabilities"] == {}
        send({
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {
                "protocolVersion": 1,
                "agentCapabilities": {},
                "agentInfo": {"name": "fake-acp", "version": "1"},
            },
        })
    elif method == "session/new":
        assert os.path.isabs(request["params"]["cwd"])
        assert request["params"]["mcpServers"] == []
        send({"jsonrpc": "2.0", "id": request["id"], "result": {"sessionId": "test-session"}})
    elif method == "session/prompt":
        assert request["params"]["prompt"][0]["type"] == "text"
        assert request["params"]["prompt"][0]["text"] == "task"
        send({
            "jsonrpc": "2.0",
            "id": "permission-request",
            "method": "session/request_permission",
            "params": {
                "sessionId": "test-session",
                "toolCall": {"toolCallId": "call-1"},
                "options": [
                    {"optionId": "allow", "name": "Allow", "kind": "allow_once"},
                    {"optionId": "reject", "name": "Reject", "kind": "reject_once"},
                ],
            },
        })
        permission = json.loads(sys.stdin.readline())
        assert permission["result"]["outcome"]["optionId"] == "reject"
        send({
            "jsonrpc": "2.0",
            "method": "session/update",
            "params": {
                "sessionId": "test-session",
                "update": {
                    "sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": "safe result"},
                },
            },
        })
        send({"jsonrpc": "2.0", "id": request["id"], "result": {"stopReason": "end_turn"}})
"""


@pytest.mark.asyncio
async def test_acp_connector_negotiates_and_rejects_agent_permissions(tmp_path):
    connector = ACPSubprocessConnector(
        [sys.executable, "-u", "-c", _FAKE_AGENT],
        cwd=tmp_path,
        timeout=3,
    )
    try:
        blocked = await connector.delegate("task")
        assert blocked["status"] == "blocked"
        assert not connector.connected

        result = await connector.delegate("task", confirmed=True)
        assert result["status"] == "completed"
        assert result["answer"] == "safe result"
        assert result["stop_reason"] == "end_turn"
        assert connector.get_task(result["task_id"]) == result
        assert connector.agent_info["name"] == "fake-acp"
        assert connector.agent_capabilities == {}
    finally:
        await connector.close()


@pytest.mark.asyncio
async def test_acp_connector_rejects_incompatible_protocol(tmp_path):
    bad_agent = (
        "import json,sys\n"
        "request=json.loads(sys.stdin.readline())\n"
        "print(json.dumps({'jsonrpc':'2.0','id':request['id'],"
        "'result':{'protocolVersion':99,'agentCapabilities':{}}}),flush=True)\n"
    )
    connector = ACPSubprocessConnector(
        [sys.executable, "-u", "-c", bad_agent],
        cwd=tmp_path,
        timeout=2,
    )
    with pytest.raises(ACPError, match="protocol version"):
        await connector.connect()
    assert not connector.connected


@pytest.mark.asyncio
async def test_acp_connector_rejects_malformed_agent_manifest(tmp_path):
    bad_agent = (
        "import json,sys\n"
        "request=json.loads(sys.stdin.readline())\n"
        "print(json.dumps({'jsonrpc':'2.0','id':request['id'],"
        "'result':{'protocolVersion':1,'agentCapabilities':{},"
        "'agentInfo':'invalid'}}),flush=True)\n"
    )
    connector = ACPSubprocessConnector(
        [sys.executable, "-u", "-c", bad_agent],
        cwd=tmp_path,
        timeout=2,
    )
    with pytest.raises(ACPError, match="invalid agentInfo"):
        await connector.connect()
    assert not connector.connected


@pytest.mark.asyncio
async def test_acp_connector_enforces_request_timeout(tmp_path):
    hanging_agent = "import sys; sys.stdin.readline(); sys.stdin.readline()"
    connector = ACPSubprocessConnector(
        [sys.executable, "-u", "-c", hanging_agent],
        cwd=tmp_path,
        timeout=0.1,
    )
    with pytest.raises(ACPError, match="timed out"):
        await connector.connect()
    assert not connector.connected


def test_acp_connector_bounds_accumulated_agent_text(tmp_path):
    connector = ACPSubprocessConnector(["unused"], cwd=tmp_path)
    connector._session_id = "test-session"
    connector._record_update(
        {
            "sessionId": "test-session",
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": "x" * (_MAX_ANSWER_BYTES + 1)},
            },
        }
    )
    answer = connector._extract_answer()
    assert answer.endswith("[ACP response truncated]")
    assert len(answer.encode()) <= _MAX_ANSWER_BYTES + len("\n[ACP response truncated]")


@pytest.mark.asyncio
async def test_acp_connector_bounds_task_history_and_objective_size(tmp_path):
    connector = ACPSubprocessConnector(["unused"], cwd=tmp_path)
    results = [await connector.delegate("task") for _ in range(_MAX_TASK_HISTORY + 1)]
    assert len(connector._tasks) == _MAX_TASK_HISTORY
    assert connector.get_task(results[0]["task_id"]) is None

    oversized = await connector.delegate("x" * _MAX_MESSAGE_BYTES, confirmed=True)
    assert oversized["status"] == "failed"
    assert "size limit" in oversized["error"]
    assert not connector.connected
