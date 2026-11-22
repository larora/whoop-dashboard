"""MCP endpoint: bearer auth and tool calls over streamable HTTP (JSON responses)."""
import json

from conftest import MCP_TOKEN
from test_sync import seed_tokens

from app.whoop import SyncRunner

HEADERS = {"Authorization": f"Bearer {MCP_TOKEN}", "Accept": "application/json, text/event-stream",
           "Content-Type": "application/json"}


def rpc(client, method, params=None, id=1):
    return client.post("/mcp", headers=HEADERS, json={"jsonrpc": "2.0", "id": id, "method": method, "params": params or {}})


def tool_result(response):
    """Tool output: structuredContent when the SDK provides it, else the JSON text block."""
    result = response.json()["result"]
    assert not result.get("isError"), result
    if "structuredContent" in result:
        sc = result["structuredContent"]
        return sc["result"] if set(sc) == {"result"} else sc
    return json.loads(result["content"][0]["text"])


def test_mcp_requires_bearer_token(client):
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                    headers={"Accept": "application/json, text/event-stream"})
    assert r.status_code == 401
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                    headers={**HEADERS, "Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_mcp_lists_tools(client):
    r = rpc(client, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}})
    assert r.status_code == 200
    r = rpc(client, "tools/list")
    names = {t["name"] for t in r.json()["result"]["tools"]}
    assert names == {"get_summary", "get_weekly", "get_daily", "get_workouts", "get_run_detail", "get_personal_bests",
                     "get_strength_detail", "get_exercise_history", "set_vo2max", "get_sync_status", "trigger_sync",
                     "get_fitness", "get_hr_stream"}


def test_mcp_summary_reflects_synced_data(client, settings, whoop):
    seed_tokens(settings)
    SyncRunner(settings, whoop.transport).run()
    r = rpc(client, "tools/call", {"name": "get_summary", "arguments": {"days": 10}})
    result = tool_result(r)
    assert result["days"] == 10 and result["avg_sleep_h"] == 6.5
    assert result["latest"]["d"] == "2026-02-20"  # cycle 49 starts 19th 18:00Z = 23:30 IST, labelled with wake-up day
    r = rpc(client, "tools/call", {"name": "get_workouts", "arguments": {"days": 36500, "sport": "run"}})
    assert len(tool_result(r)) == 50


def test_mcp_token_in_path(client):
    """Claude.ai's connector form can't set headers, so the token may come in the URL instead."""
    h = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    assert client.post(f"/mcp/{MCP_TOKEN}", headers=h, json=body).status_code == 200
    assert client.post("/mcp/wrong-token", headers=h, json=body).status_code == 401
