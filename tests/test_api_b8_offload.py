"""B8 事件循环阻塞回归测试。

覆盖：parse_screenshot / ai_chat / backup_preflight / backup_restore / parse_csv
五个 async 端点把同步重活（视觉模型 HTTP、持仓上下文构建、zip 校验/恢复、
pandas 解析）经 anyio.to_thread.run_sync  offload 到线程；SSE 流式契约不被
破坏；异常跨线程仍映射正确 HTTP 状态码；重活期间事件循环保持可调度
（并发 ticker 检测）；lifespan 调度器降级走公共 reset_scheduler。
"""
from __future__ import annotations

import io
import json
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock

import anyio
import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile

from zfundpilot import api, backup_service, config, db, scheduler


@pytest.fixture
def temp_db(monkeypatch):
    with TemporaryDirectory() as d:
        monkeypatch.setattr(config, "DB_PATH", str(Path(d) / "test.db"))
        monkeypatch.setattr(config, "AUTH_DATA_PATH", str(Path(d) / "auth.json"))
        db.init_db()
        yield


@pytest.fixture
def client(temp_db, monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    monkeypatch.setattr(api, "_REQ_LOGS", {})
    monkeypatch.setattr(api, "_AGENT_REQ_LOGS", {})
    return TestClient(api.app)


@pytest.fixture
def thread_spy(monkeypatch):
    """记录经 anyio.to_thread.run_sync offload 的函数（委托真实实现）。"""
    calls: list = []
    real = anyio.to_thread.run_sync

    async def spy(func, *args, **kwargs):
        calls.append(func)
        return await real(func, *args, **kwargs)

    monkeypatch.setattr(anyio.to_thread, "run_sync", spy)
    return calls


# ---------------------------------------------------------------------------
# offload 接线：重活必须经 to_thread，且参数/返回值契约不变
# ---------------------------------------------------------------------------

class TestOffloadWiring:
    def test_parse_screenshot_offloaded(self, client, thread_spy, monkeypatch):
        fake = MagicMock(return_value={"ok": True, "items": []})
        monkeypatch.setattr(api.ai, "parse_screenshot", fake)
        resp = client.post(
            "/api/ai/parse-screenshot",
            files={"file": ("a.png", b"fake-image", "image/png")})
        assert resp.status_code == 200, resp.text
        assert fake in thread_spy
        # 重复标记（同步 DB 查询）同样 offload
        assert api._mark_duplicates in thread_spy
        args = fake.call_args[0]
        assert args[0] == b"fake-image"
        assert args[1] == "transactions"
        assert args[3] == "image/png"

    def test_parse_screenshot_holdings_skips_duplicates(
            self, client, thread_spy, monkeypatch):
        fake = MagicMock(return_value={"ok": True, "items": []})
        monkeypatch.setattr(api.ai, "parse_screenshot", fake)
        resp = client.post(
            "/api/ai/parse-screenshot?mode=holdings",
            files={"file": ("a.png", b"fake-image", "image/png")})
        assert resp.status_code == 200, resp.text
        assert fake in thread_spy
        assert api._mark_duplicates not in thread_spy

    def test_ai_chat_context_offloaded_and_sse_intact(
            self, client, thread_spy, monkeypatch):
        build = MagicMock(return_value="CTX")
        monkeypatch.setattr(api.ai, "build_portfolio_context", build)
        seen: dict = {}

        async def fake_stream(messages, context):
            seen["context"] = context
            yield json.dumps({"content": "你好"})

        monkeypatch.setattr(api.ai, "chat_stream", fake_stream)
        resp = client.post("/api/ai/chat", json={
            "messages": [{"role": "user", "content": "分析持仓"}]})
        assert resp.status_code == 200, resp.text
        assert build in thread_spy
        assert seen["context"] == "CTX"
        assert resp.headers["content-type"].startswith("text/event-stream")
        assert '"content"' in resp.text
        assert resp.text.rstrip().endswith("data: [DONE]")

    def test_ai_chat_with_system_skips_context_build(
            self, client, thread_spy, monkeypatch):
        build = MagicMock(return_value="CTX")
        monkeypatch.setattr(api.ai, "build_portfolio_context", build)
        seen: dict = {}

        async def fake_stream(messages, context):
            seen["context"] = context
            yield json.dumps({"content": "ok"})

        monkeypatch.setattr(api.ai, "chat_stream", fake_stream)
        resp = client.post("/api/ai/chat", json={"messages": [
            {"role": "system", "content": "已有上下文"},
            {"role": "user", "content": "hi"},
        ]})
        assert resp.status_code == 200, resp.text
        build.assert_not_called()
        assert build not in thread_spy
        assert seen["context"] == ""

    def test_backup_preflight_offloaded(self, client, thread_spy, monkeypatch):
        preview = SimpleNamespace(
            total_rows=3, format_version=2,
            to_dict=lambda: {"total_rows": 3, "format_version": 2})
        fake = MagicMock(return_value=preview)
        monkeypatch.setattr(api.backup_service, "preview_backup", fake)
        resp = client.post(
            "/api/backup/preflight",
            files={"file": ("b.zip", b"zip-bytes", "application/zip")})
        assert resp.status_code == 200, resp.text
        assert fake in thread_spy
        assert fake.call_args[0] == (b"zip-bytes",)
        assert resp.json()["total_rows"] == 3

    def test_backup_restore_offloaded(self, client, thread_spy, monkeypatch):
        result = SimpleNamespace(to_dict=lambda: {"ok": True, "restored_rows": 5})
        fake = MagicMock(return_value=result)
        monkeypatch.setattr(api.backup_service, "restore_backup", fake)
        monkeypatch.setattr(config, "apply_agent_write_preference", lambda v: None)
        resp = client.post(
            "/api/backup/restore",
            files={"file": ("b.zip", b"zip-bytes", "application/zip")},
            data={"confirmation": "RESTORE"})
        assert resp.status_code == 200, resp.text
        # restore_backup 经 functools.partial 包装（携带 ip/username kwargs）
        assert any(getattr(c, "func", c) is fake for c in thread_spy)
        # partial 透传 ip/username 关键字参数
        assert fake.call_args[0] == (b"zip-bytes",)
        assert "ip" in fake.call_args.kwargs
        assert "username" in fake.call_args.kwargs
        assert resp.json()["ok"] is True

    def test_restore_validation_error_maps_422_across_thread(
            self, client, monkeypatch):
        exc = backup_service.BackupValidationError("bad_zip", "备份损坏")
        monkeypatch.setattr(api.backup_service, "restore_backup",
                            MagicMock(side_effect=exc))
        resp = client.post(
            "/api/backup/restore",
            files={"file": ("b.zip", b"zip-bytes", "application/zip")},
            data={"confirmation": "RESTORE"})
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "bad_zip"

    def test_restore_busy_maps_409_across_thread(self, client, monkeypatch):
        monkeypatch.setattr(api.backup_service, "restore_backup",
                            MagicMock(side_effect=backup_service.BackupBusyError("占用")))
        resp = client.post(
            "/api/backup/restore",
            files={"file": ("b.zip", b"zip-bytes", "application/zip")},
            data={"confirmation": "RESTORE"})
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "restore_busy"

    def test_parse_csv_offloaded(self, client, thread_spy, monkeypatch):
        fake = MagicMock(return_value=([], []))
        monkeypatch.setattr(api.data_io, "parse_transactions_csv", fake)
        resp = client.post(
            "/api/csv/parse",
            files={"file": ("t.csv", b"date,fund_code\n", "text/csv")})
        assert resp.status_code == 200, resp.text
        assert fake in thread_spy
        assert fake.call_args[0] == (b"date,fund_code\n",)
        assert resp.json() == {"transactions": [], "errors": []}


# ---------------------------------------------------------------------------
# 事件循环不被冻结：重活期间并发 ticker 仍能推进
# （直接调用端点协程，与真实请求共用同一事件循环语义）
# ---------------------------------------------------------------------------

async def _run_with_ticker(endpoint_coro):
    """在事件循环上运行端点协程，同时统计 10ms ticker 推进次数。"""
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            ticks += 1
            await anyio.sleep(0.01)

    async with anyio.create_task_group() as tg:
        tg.start_soon(ticker)
        result = await endpoint_coro
        tg.cancel_scope.cancel()
    return result, ticks


@pytest.mark.anyio
async def test_parse_screenshot_keeps_loop_responsive(monkeypatch):
    def heavy(image, mode, channel_hint, content_type, user_hint):
        time.sleep(0.3)  # 模拟慢视觉模型的同步 HTTP（最长 60s）
        return {"ok": False, "items": [], "error": "slow"}

    monkeypatch.setattr(api.ai, "parse_screenshot", heavy)
    file = UploadFile(file=io.BytesIO(b"img"), filename="a.png")
    result, ticks = await _run_with_ticker(api.parse_screenshot(file=file))
    assert result["ok"] is False
    # 若同步重活阻塞事件循环，ticker 几乎无法推进
    assert ticks >= 5


@pytest.mark.anyio
async def test_ai_chat_context_build_keeps_loop_responsive(monkeypatch):
    def heavy_context():
        time.sleep(0.3)  # 模拟 DB + akshare 行情同步抓取
        return "CTX"

    monkeypatch.setattr(api.ai, "build_portfolio_context", heavy_context)
    seen: dict = {}

    async def fake_stream(messages, context):
        seen["context"] = context
        yield json.dumps({"content": "ok"})

    monkeypatch.setattr(api.ai, "chat_stream", fake_stream)
    body = api.ChatRequest(messages=[api.ChatMessage(role="user", content="hi")])

    async def call():
        resp = await api.ai_chat(body)
        chunks = [chunk async for chunk in resp.body_iterator]
        return chunks

    chunks, ticks = await _run_with_ticker(call())
    assert seen["context"] == "CTX"
    assert ticks >= 5
    assert chunks[-1] == "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# IPv6 信任代理网段端到端：env 风格解析 → _get_client_ip 信任判定
# ---------------------------------------------------------------------------

class TestIpv6TrustedProxy:
    def test_ipv6_cidr_proxy_honors_xff(self, monkeypatch):
        monkeypatch.setattr(config, "TRUSTED_PROXIES",
                            config._parse_trusted_proxies("2001:db8::/32"))
        req = SimpleNamespace(client=SimpleNamespace(host="2001:db8::1"),
                              headers={"x-forwarded-for": "203.0.113.9"})
        assert api._get_client_ip(req) == "203.0.113.9"

    def test_ipv4_mapped_hits_ipv4_cidr_from_parser(self, monkeypatch):
        monkeypatch.setattr(config, "TRUSTED_PROXIES",
                            config._parse_trusted_proxies("127.0.0.0/8"))
        req = SimpleNamespace(client=SimpleNamespace(host="::ffff:127.0.0.1"),
                              headers={"x-forwarded-for": "203.0.113.9"})
        assert api._get_client_ip(req) == "203.0.113.9"

    def test_ipv6_outside_cidr_ignores_xff(self, monkeypatch):
        monkeypatch.setattr(config, "TRUSTED_PROXIES",
                            config._parse_trusted_proxies("2001:db8::/32"))
        req = SimpleNamespace(client=SimpleNamespace(host="2001:db9::1"),
                              headers={"x-forwarded-for": "203.0.113.9"})
        assert api._get_client_ip(req) == "2001:db9::1"


# ---------------------------------------------------------------------------
# lifespan 调度器降级：非法 cron → 公共 reset_scheduler 清理半初始化实例后重建
# ---------------------------------------------------------------------------

class TestLifespanSchedulerReset:
    def test_bad_cron_fallback_rebuilds_via_public_reset(self, temp_db, monkeypatch):
        # 隔离 lifespan 的全局副作用与后台任务
        monkeypatch.setattr(config, "AUTH_ENABLED", False)
        monkeypatch.setattr(config, "apply_agent_write_preference", lambda v: None)
        monkeypatch.setattr(api, "_REQ_LOGS", {})
        monkeypatch.setattr(api, "_AGENT_REQ_LOGS", {})
        monkeypatch.setattr(api.analysis, "recalculate_t1_transactions", lambda: [])
        monkeypatch.setattr(api.refresh_service, "mark_interrupted_on_startup", lambda: 0)
        monkeypatch.setattr(api.proposal_service, "mark_stale_on_startup", lambda: 0)
        monkeypatch.setattr(scheduler, "purge_agent_operations_daily", lambda: 0)
        # 避免真实引导线程联网/执行任务
        monkeypatch.setattr(scheduler, "_get_enabled", lambda: False)
        monkeypatch.setattr(scheduler, "_get_dividend_enabled", lambda: False)
        monkeypatch.setattr(scheduler, "_bootstrap_auto_invest", lambda: None)
        monkeypatch.setattr(scheduler, "_bootstrap_risk_levels", lambda: None)
        monkeypatch.setattr(scheduler, "_scheduler", None)
        # 非法 cron：init_scheduler 创建实例后 _parse_cron 抛 ValueError
        db.upsert_preference("nav_cron", "99 99 * * *")
        reset_spy = MagicMock(wraps=scheduler.reset_scheduler)
        monkeypatch.setattr(scheduler, "reset_scheduler", reset_spy)

        with TestClient(api.app):
            # 降级成功：调度器以默认 cron 重建并运行
            assert scheduler._scheduler is not None
            assert scheduler._scheduler.running
            assert db.get_preference("nav_cron") == config.NAV_CRON
        reset_spy.assert_called_once()
        # 退出 lifespan 正常停止
        assert scheduler._scheduler is None
