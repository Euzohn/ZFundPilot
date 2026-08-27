"""视觉解析测试：名称→代码解析、JSON 提取、代码后处理、截图解析流程。"""
from unittest.mock import MagicMock, patch

from zfundpilot import ai, fund_filter

# ---------------------------------------------------------------------------
# resolve_fund_code / verify_fund_code
# ---------------------------------------------------------------------------
UNIVERSE = [
    {"code": "005827", "name": "易方达蓝筹精选混合", "type": "混合", "sector": "权益"},
    {"code": "005828", "name": "易方达蓝筹精选混合A", "type": "混合", "sector": "权益"},
    {"code": "005829", "name": "易方达蓝筹精选混合C", "type": "混合", "sector": "权益"},
    {"code": "003095", "name": "中欧医疗健康混合A", "type": "混合", "sector": "医疗"},
    {"code": "110011", "name": "易方达中小盘混合", "type": "混合", "sector": "权益"},
]


def _mock_universe():
    return patch("zfundpilot.fund_filter.load_fund_universe", return_value=UNIVERSE)


class TestResolveFundCode:
    def test_exact_match(self):
        with _mock_universe():
            r = fund_filter.resolve_fund_code("易方达蓝筹精选混合")
        assert r["status"] == "exact"
        assert r["code"] == "005827"

    def test_exact_match_with_class_suffix(self):
        with _mock_universe():
            r = fund_filter.resolve_fund_code("易方达蓝筹精选混合A")
        assert r["status"] == "exact"
        assert r["code"] == "005828"

    def test_multiple_candidates_substring(self):
        """「易方达蓝筹精选」是多个基金子串 → multiple。"""
        with _mock_universe():
            r = fund_filter.resolve_fund_code("易方达蓝筹精选")
        assert r["status"] == "multiple"
        assert len(r["candidates"]) >= 3

    def test_single_substring_match(self):
        """「中欧医疗健康」只匹配一只 → exact。"""
        with _mock_universe():
            r = fund_filter.resolve_fund_code("中欧医疗健康")
        assert r["status"] == "exact"
        assert r["code"] == "003095"

    def test_no_match(self):
        with _mock_universe():
            r = fund_filter.resolve_fund_code("完全不存在的基金名称")
        assert r["status"] == "none"
        assert r["code"] is None

    def test_class_suffix_normalization(self):
        """「易方达蓝筹精选混合D」→ 去掉 D 后精确匹配。"""
        with _mock_universe():
            r = fund_filter.resolve_fund_code("易方达蓝筹精选混合D")
        assert r["status"] == "exact"
        assert r["code"] == "005827"

    def test_empty_name(self):
        with _mock_universe():
            r = fund_filter.resolve_fund_code("")
        assert r["status"] == "none"

    def test_universe_empty(self):
        with patch("zfundpilot.fund_filter.load_fund_universe", return_value=[]):
            r = fund_filter.resolve_fund_code("易方达蓝筹精选混合")
        assert r["status"] == "none"


class TestVerifyFundCode:
    def test_valid_code(self):
        with _mock_universe():
            assert fund_filter.verify_fund_code("005827") is True

    def test_invalid_code(self):
        with _mock_universe():
            assert fund_filter.verify_fund_code("999999") is False

    def test_empty(self):
        with _mock_universe():
            assert fund_filter.verify_fund_code("") is False


# ---------------------------------------------------------------------------
# _extract_json_list
# ---------------------------------------------------------------------------
class TestExtractJsonList:
    def test_json_block(self):
        content = '```json\n[{"fund_name": "测试"}]\n```'
        assert ai._extract_json_list(content) == [{"fund_name": "测试"}]

    def test_bare_json(self):
        content = '[{"fund_name": "测试"}]'
        assert ai._extract_json_list(content) == [{"fund_name": "测试"}]

    def test_json_with_surrounding_text(self):
        content = '识别到以下交易：\n[{"fund_name": "测试"}]\n以上是结果。'
        assert ai._extract_json_list(content) == [{"fund_name": "测试"}]

    def test_not_json(self):
        assert ai._extract_json_list("这不是 JSON") is None

    def test_empty_array(self):
        assert ai._extract_json_list("[]") == []

    def test_object_not_array(self):
        # 单个对象不是数组 → None
        assert ai._extract_json_list('{"a": 1}') is None


# ---------------------------------------------------------------------------
# _resolve_codes
# ---------------------------------------------------------------------------
class TestResolveCodes:
    def test_valid_code_kept(self):
        items = [{"fund_name": "易方达蓝筹精选混合", "fund_code": "005827"}]
        with _mock_universe():
            result = ai._resolve_codes(items)
        assert result[0]["fund_code"] == "005827"
        assert result[0]["code_status"] == "exact"

    def test_invalid_code_discarded(self):
        """模型编造的 code 不在 universe → 丢弃，走名称匹配。"""
        items = [{"fund_name": "易方达蓝筹精选混合", "fund_code": "999999"}]
        with _mock_universe():
            result = ai._resolve_codes(items)
        assert result[0]["fund_code"] == "005827"
        assert result[0]["code_status"] == "exact"

    def test_no_code_resolve_by_name(self):
        items = [{"fund_name": "易方达蓝筹精选混合", "fund_code": None}]
        with _mock_universe():
            result = ai._resolve_codes(items)
        assert result[0]["fund_code"] == "005827"
        assert result[0]["code_status"] == "exact"

    def test_multiple_candidates(self):
        items = [{"fund_name": "易方达蓝筹精选", "fund_code": None}]
        with _mock_universe():
            result = ai._resolve_codes(items)
        assert result[0]["code_status"] == "multiple"
        assert result[0]["fund_code"] is None
        assert len(result[0]["candidates"]) >= 3

    def test_no_match(self):
        items = [{"fund_name": "不存在的基金", "fund_code": None}]
        with _mock_universe():
            result = ai._resolve_codes(items)
        assert result[0]["code_status"] == "none"
        assert result[0]["fund_code"] is None


# ---------------------------------------------------------------------------
# parse_screenshot
# ---------------------------------------------------------------------------
class TestParseScreenshot:
    def test_unconfigured(self):
        """未配置视觉模型 → 返回错误。"""
        with patch("zfundpilot.ai.config") as mock_cfg:
            mock_cfg.AI_VISION_BASE_URL = ""
            mock_cfg.AI_VISION_API_KEY = ""
            mock_cfg.AI_VISION_MODEL = ""
            r = ai.parse_screenshot(b"img", "transactions")
        assert r["ok"] is False
        assert "未配置" in r["error"]

    def test_success_transactions_mode(self):
        """mock httpx → 返回解析列表。"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": '```json\n[{"fund_name": "易方达蓝筹精选混合", "fund_code": "005827", "action": "buy", "amount": 1000}]```'}}]
        }
        with patch("zfundpilot.ai.config") as mock_cfg, \
             patch("zfundpilot.ai.httpx.post", return_value=mock_resp), \
             _mock_universe():
            mock_cfg.AI_VISION_BASE_URL = "https://api.test.com/v1"
            mock_cfg.AI_VISION_API_KEY = "sk-test"
            mock_cfg.AI_VISION_MODEL = "test-vl"
            r = ai.parse_screenshot(b"img", "transactions")
        assert r["ok"] is True
        assert len(r["items"]) == 1
        assert r["items"][0]["fund_code"] == "005827"
        assert r["items"][0]["code_status"] == "exact"

    def test_success_holdings_mode(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": '[{"fund_name": "易方达蓝筹精选混合", "fund_code": null, "shares": 500}]'}}]
        }
        with patch("zfundpilot.ai.config") as mock_cfg, \
             patch("zfundpilot.ai.httpx.post", return_value=mock_resp), \
             _mock_universe():
            mock_cfg.AI_VISION_BASE_URL = "https://api.test.com/v1"
            mock_cfg.AI_VISION_API_KEY = "sk-test"
            mock_cfg.AI_VISION_MODEL = "test-vl"
            r = ai.parse_screenshot(b"img", "holdings")
        assert r["ok"] is True
        assert r["items"][0]["fund_code"] == "005827"

    def test_api_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"
        with patch("zfundpilot.ai.config") as mock_cfg, \
             patch("zfundpilot.ai.httpx.post", return_value=mock_resp):
            mock_cfg.AI_VISION_BASE_URL = "https://api.test.com/v1"
            mock_cfg.AI_VISION_API_KEY = "sk-test"
            mock_cfg.AI_VISION_MODEL = "test-vl"
            r = ai.parse_screenshot(b"img", "transactions")
        assert r["ok"] is False
        assert "401" in r["error"]

    def test_unparseable_content(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "这不是JSON"}}]
        }
        with patch("zfundpilot.ai.config") as mock_cfg, \
             patch("zfundpilot.ai.httpx.post", return_value=mock_resp):
            mock_cfg.AI_VISION_BASE_URL = "https://api.test.com/v1"
            mock_cfg.AI_VISION_API_KEY = "sk-test"
            mock_cfg.AI_VISION_MODEL = "test-vl"
            r = ai.parse_screenshot(b"img", "transactions")
        assert r["ok"] is False
        assert "JSON" in r["error"]


# ---------------------------------------------------------------------------
# test_vision_connection
# ---------------------------------------------------------------------------
class TestTestVisionConnection:
    def test_unconfigured(self):
        with patch("zfundpilot.ai.config") as mock_cfg:
            mock_cfg.AI_VISION_BASE_URL = ""
            mock_cfg.AI_VISION_API_KEY = ""
            mock_cfg.AI_VISION_MODEL = ""
            r = ai.test_vision_connection()
        assert r["ok"] is False

    def test_success(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("zfundpilot.ai.config") as mock_cfg, \
             patch("zfundpilot.ai.httpx.post", return_value=mock_resp):
            mock_cfg.AI_VISION_BASE_URL = "https://api.test.com/v1"
            mock_cfg.AI_VISION_API_KEY = "sk-test"
            mock_cfg.AI_VISION_MODEL = "test-vl"
            r = ai.test_vision_connection()
        assert r["ok"] is True
        assert r["model"] == "test-vl"


# ---------------------------------------------------------------------------
# _mark_duplicates（API 层重复交易检测）
# ---------------------------------------------------------------------------
class TestMarkDuplicates:
    def _call(self, items, existing_txs):
        from zfundpilot import api as api_module
        from zfundpilot.models import Transaction

        tx_objs = [Transaction(**{**tx, "id": i + 1}) for i, tx in enumerate(existing_txs)]
        with patch("zfundpilot.api.db") as mock_db:
            mock_db.get_transactions.return_value = tx_objs
            api_module._mark_duplicates(items)
        return items

    def test_duplicate_buy(self):
        """同基金同日同金额 → 重复。"""
        items = [{"fund_code": "005827", "action": "buy", "date": "2026-01-01", "amount": 1000.0, "shares": None}]
        existing = [{"fund_code": "005827", "action": "buy", "date": "2026-01-01", "amount": 1000.0, "shares": 500, "nav": 2.0, "fee": 0}]
        result = self._call(items, existing)
        assert result[0]["is_duplicate"] is True

    def test_different_amount_not_duplicate(self):
        """同基金同日不同金额 → 非重复。"""
        items = [{"fund_code": "005827", "action": "buy", "date": "2026-01-01", "amount": 2000.0, "shares": None}]
        existing = [{"fund_code": "005827", "action": "buy", "date": "2026-01-01", "amount": 1000.0, "shares": 500, "nav": 2.0, "fee": 0}]
        result = self._call(items, existing)
        assert result[0]["is_duplicate"] is False

    def test_different_date_not_duplicate(self):
        """同基金不同日 → 非重复。"""
        items = [{"fund_code": "005827", "action": "buy", "date": "2026-01-02", "amount": 1000.0, "shares": None}]
        existing = [{"fund_code": "005827", "action": "buy", "date": "2026-01-01", "amount": 1000.0, "shares": 500, "nav": 2.0, "fee": 0}]
        result = self._call(items, existing)
        assert result[0]["is_duplicate"] is False

    def test_duplicate_by_shares(self):
        """卖出按 shares 匹配。"""
        items = [{"fund_code": "005827", "action": "sell", "date": "2026-02-01", "amount": None, "shares": 200.0}]
        existing = [{"fund_code": "005827", "action": "sell", "date": "2026-02-01", "amount": 600.0, "shares": 200.0, "nav": 3.0, "fee": 0}]
        result = self._call(items, existing)
        assert result[0]["is_duplicate"] is True

    def test_no_date_not_checked(self):
        """date 为 null → 不检测（is_duplicate=False）。"""
        items = [{"fund_code": "005827", "action": "buy", "date": None, "amount": 1000.0, "shares": None}]
        existing = [{"fund_code": "005827", "action": "buy", "date": "2026-01-01", "amount": 1000.0, "shares": 500, "nav": 2.0, "fee": 0}]
        result = self._call(items, existing)
        assert result[0]["is_duplicate"] is False

    def test_no_existing_not_duplicate(self):
        """DB 无交易 → 全部非重复。"""
        items = [{"fund_code": "005827", "action": "buy", "date": "2026-01-01", "amount": 1000.0, "shares": None}]
        result = self._call(items, [])
        assert result[0]["is_duplicate"] is False

    def test_amount_tolerance(self):
        """金额 0.01 容差内 → 重复。"""
        items = [{"fund_code": "005827", "action": "buy", "date": "2026-01-01", "amount": 1000.005, "shares": None}]
        existing = [{"fund_code": "005827", "action": "buy", "date": "2026-01-01", "amount": 1000.0, "shares": 500, "nav": 2.0, "fee": 0}]
        result = self._call(items, existing)
        assert result[0]["is_duplicate"] is True
