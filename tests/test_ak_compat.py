"""akshare 跨版本改名兼容层测试。"""

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from zfundpilot import ak_compat


def _fake_ak(**attrs) -> ModuleType:
    module = ModuleType("akshare")
    for name, value in attrs.items():
        setattr(module, name, value)
    return module


def test_resolve_prefers_new_name():
    new = MagicMock(name="new")
    old = MagicMock(name="old")
    with patch.dict(
        sys.modules,
        {"akshare": _fake_ak(index_zh_daily_sina=new, stock_zh_index_daily=old)},
    ):
        assert ak_compat.resolve("index_zh_daily_sina", "stock_zh_index_daily") is new


def test_resolve_falls_back_to_legacy_name():
    old = MagicMock(name="old")
    with patch.dict(
        sys.modules, {"akshare": _fake_ak(stock_zh_index_daily=old)}
    ):
        assert ak_compat.resolve("index_zh_daily_sina", "stock_zh_index_daily") is old


def test_resolve_all_missing_raises():
    with patch.dict(sys.modules, {"akshare": _fake_ak()}):
        with pytest.raises(AttributeError, match="index_zh_daily_sina"):
            ak_compat.resolve("index_zh_daily_sina", "stock_zh_index_daily")


def test_call_passes_kwargs_to_resolved_function():
    new = MagicMock(return_value="df")
    with patch.dict(sys.modules, {"akshare": _fake_ak(index_zh_daily_sina=new)}):
        result = ak_compat.call(
            "index_zh_daily_sina",
            "stock_zh_index_daily",
            symbol="sh000300",
        )

    assert result == "df"
    new.assert_called_once_with(symbol="sh000300")
