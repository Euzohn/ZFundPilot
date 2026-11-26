"""AI 设置与流式联网搜索回归测试。"""

import asyncio
import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient

from zfundpilot import ai, api, config
from zfundpilot.api import app


@pytest.fixture
def ai_client(monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    monkeypatch.setattr(config, "AI_BASE_URL", "")
    monkeypatch.setattr(config, "AI_API_KEY", "")
    monkeypatch.setattr(config, "AI_MODEL", "")
    monkeypatch.setattr(config, "AI_WEB_SEARCH", False)
    return TestClient(app)


def test_first_connection_uses_unsaved_settings(ai_client, monkeypatch):
    calls = []

    def post(url, *, headers, json, timeout):
        calls.append((url, headers["Authorization"], json["model"]))
        return httpx.Response(200)

    monkeypatch.setattr(ai.httpx, "post", post)
    response = ai_client.post("/api/ai/test", json={
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "draft-key",
        "model": "deepseek-flash",
        "web_search": True,
    })

    assert response.status_code == 200
    assert response.json() == {
        "ok": True, "provider": "deepseek", "model": "deepseek-flash", "has_search": True,
    }
    assert calls == [
        ("https://api.deepseek.com/v1/chat/completions", "Bearer draft-key", "deepseek-flash"),
    ]
    assert ai_client.get("/api/settings/ai").json()["has_key"] is False
    assert config.AI_BASE_URL == ""


@pytest.mark.parametrize("base_url, expected_key", [
    (None, "Bearer saved-key"),
    ("https://api.deepseek.com/v1/", "Bearer saved-key"),
    ("https://different.example/v1", None),
])
def test_connection_only_reuses_key_for_saved_endpoint(ai_client, monkeypatch, base_url, expected_key):
    monkeypatch.setattr(config, "AI_BASE_URL", "https://api.deepseek.com/v1")
    monkeypatch.setattr(config, "AI_API_KEY", "saved-key")
    monkeypatch.setattr(config, "AI_MODEL", "deepseek-flash")
    calls = []

    def post(url, *, headers, json, timeout):
        calls.append(headers["Authorization"])
        return httpx.Response(200)

    monkeypatch.setattr(ai.httpx, "post", post)
    payload = {"base_url": base_url, "model": "deepseek-flash"} if base_url else None
    response = ai_client.post("/api/ai/test", json=payload)

    assert response.json()["ok"] is (expected_key is not None)
    assert calls == ([expected_key] if expected_key else [])


@pytest.mark.parametrize("base_url, model, enabled, expected_tool", [
    ("https://api.deepseek.com/v1", "deepseek-flash", True, "deepseek_web_search"),
    ("https://api.deepseek.com/v1", "deepseek-flash", False, None),
    ("https://api.deepseek.com/v1", "deepseek-chat", True, None),
    ("https://deepseek.example/v1", "deepseek-flash", True, None),
])
def test_deepseek_chat_uses_tools_supported_by_endpoint(
    monkeypatch, base_url, model, enabled, expected_tool,
):
    monkeypatch.setattr(config, "AI_BASE_URL", base_url)
    monkeypatch.setattr(config, "AI_API_KEY", "test-key")
    monkeypatch.setattr(config, "AI_MODEL", model)
    monkeypatch.setattr(config, "AI_WEB_SEARCH", enabled)
    request_bodies = []

    def respond(request):
        body = json.loads(request.content)
        request_bodies.append(body)
        if any(tool["type"] != "deepseek_web_search" for tool in body.get("tools", [])):
            return httpx.Response(422, json={"error": {"message": "unknown variant web_search"}})
        choices = [{"delta": {"content": "回答"}}]
        events = []
        if body.get("tools"):
            events.append({"choices": [{"delta": {}, "server_tool_event": {"type": "call_started"}}]})
        events.append({"choices": choices})
        lines = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
        return httpx.Response(200, text=lines + "data: [DONE]\n\n")

    async_client = httpx.AsyncClient
    monkeypatch.setattr(ai.httpx, "AsyncClient", lambda **kwargs: async_client(
        transport=httpx.MockTransport(respond), **kwargs,
    ))

    async def collect():
        return [
            json.loads(event)
            async for event in ai.chat_stream([{"role": "user", "content": "请搜索最新资讯"}], "")
        ]

    events = asyncio.run(collect())
    if expected_tool:
        assert request_bodies[0]["tools"] == [{"type": "deepseek_web_search"}]
        assert events == [{"status": "searching"}, {"content": "回答"}, {"done": True}]
    else:
        assert "tools" not in request_bodies[0]
        assert events == [{"content": "回答"}, {"done": True}]
    assert len(request_bodies) == 1


@pytest.mark.parametrize("sent_at, expected", [
    ("2026-11-26T16:01:23Z", "2026-11-27 00:01+08:00"),
    (None, "2026-11-27 00:03+08:00"),
])
def test_chat_sends_one_local_timestamp_for_current_message(ai_client, monkeypatch, sent_at, expected):
    monkeypatch.setattr(config, "TIMEZONE", ZoneInfo("Asia/Shanghai"))
    monkeypatch.setattr(config, "AI_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setattr(config, "AI_API_KEY", "test-key")
    monkeypatch.setattr(config, "AI_MODEL", "test-model")
    requests = []

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 26, 16, 3, tzinfo=UTC).astimezone(tz)

    monkeypatch.setattr(api, "datetime", FixedDateTime)

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, text="data: [DONE]\n\n")

    async_client = httpx.AsyncClient
    monkeypatch.setattr(ai.httpx, "AsyncClient", lambda **kwargs: async_client(
        transport=httpx.MockTransport(respond), **kwargs,
    ))
    history = [
        {"role": "system", "content": "固定提示词"},
        {"role": "user", "content": "今天的行情"},
        {"role": "assistant", "content": "回答"},
    ]
    payload = {"messages": [*history, {"role": "user", "content": "昨天的呢"}]}
    if sent_at is not None:
        payload["sent_at"] = sent_at
    response = ai_client.post("/api/ai/chat", json=payload)

    assert response.status_code == 200
    assert len(requests) == 1
    assert requests[0]["messages"] == [
        *history,
        {"role": "user", "content": f"[本轮发送时间 {expected}]\n昨天的呢"},
    ]
    assert "sent_at" not in requests[0]
