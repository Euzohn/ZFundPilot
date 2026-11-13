"""指数型基金分类（index_tag）测试：宽基/行业/主题判定与边界。"""
from __future__ import annotations

import pytest

from zfundpilot import fund_filter
from zfundpilot.fetch_fund import _classify_index


# ---------------------------------------------------------------------------
# _classify_index 规则
# ---------------------------------------------------------------------------
class TestClassifyIndex:
    @pytest.mark.parametrize("name,ftype,want", [
        # 宽基
        ("嘉实中证500ETF联接A", "指数型", "broad"),
        ("华夏沪深300ETF联接A", "指数型", "broad"),
        ("华安沪深300增强A", "指数型", "broad"),
        ("易方达上证50增强A", "指数型", "broad"),
        ("华夏创业板50ETF联接C", "指数型", "broad"),
        ("天弘中证A500ETF联接A", "指数型", "broad"),
        ("南方恒生国企ETF联接A", "指数型", "broad"),
        # 海外宽基（多数被归类为 QDII）
        ("广发纳斯达克100ETF联接美元(QDII)A", "QDII", "broad"),
        ("博时标普500ETF联接(QDII)A", "QDII", "broad"),
        ("华安德国(DAX)联接(QDII)A", "QDII", "broad"),
        ("华安日经225ETF联接(QDII)A", "QDII", "broad"),
        # 行业
        ("南方中证500信息技术联接A", "指数型", "sector"),
        ("广发中证全指可选消费联接A", "指数型", "sector"),
        ("天弘中证医药100A", "指数型", "sector"),
        ("博时黄金D", "指数型", "sector"),
        ("华夏中证沪深港黄金产业股票ETF发起式联接A", "指数型", "sector"),
        ("易方达标普信息科技指数(QDII-LOF)A(美元现汇)", "QDII", "sector"),
        ("摩根富时发达市场REITs指数(QDII)人民币A", "QDII", "sector"),
        # 主题/策略
        ("华夏恒生科技ETF联接A", "指数型", "theme"),
        ("易方达中证人工智能ETF联接A", "指数型", "theme"),
        ("天弘中证红利低波动A", "指数型", "theme"),
        ("富国中证国企改革(LOF)C", "指数型", "theme"),
        ("易方达中证海外互联网50ETF联接(QDII)A", "QDII", "theme"),
        # 非指数型不打标
        ("易方达蓝筹精选混合", "混合型", ""),
        ("华夏成长混合", "混合型", ""),
        ("招商中证白酒指数A", "债券型", ""),
        # 债券指数不参与股性分类
        ("易方达中债3-5年期国债指数", "指数型", ""),
        # 主动 QDII（名称无指数信号）不打标
        ("嘉实全球互联网股票人民币", "QDII", ""),
        ("华夏全球股票(QDII)(人民币)", "QDII", ""),
        # LOF 类型映射误判的主动基金不打标
        ("中欧盛世成长混合(LOF)E", "指数型", ""),
        ("金鹰先进制造股票(LOF)C", "指数型", ""),
        # 无法判断的冷门指数不打标
        ("某基金未知指数A", "指数型", ""),
        ("", "指数型", ""),
    ])
    def test_classification(self, name, ftype, want):
        assert _classify_index(name, ftype) == want

    def test_narrow_index_beats_broad_keyword(self):
        """「中证500信息技术」这类窄基应归行业，宽基词不能抢先命中。"""
        assert _classify_index("南方中证500信息技术联接A", "指数型") == "sector"
        assert _classify_index("易方达沪深300医药ETF联接A", "指数型") == "sector"

    def test_empty_fund_type(self):
        assert _classify_index("嘉实中证500ETF联接A") == ""


# ---------------------------------------------------------------------------
# filter_funds 集成：index_tag 出现在返回项中
# ---------------------------------------------------------------------------
_UNIVERSE = [
    {"code": "000001", "name": "华夏成长混合", "type": "混合型", "sector": "其它"},
    {"code": "000051", "name": "华夏沪深300ETF联接A", "type": "指数型", "sector": "沪深300"},
    {"code": "000059", "name": "国联安中证医药100A", "type": "指数型", "sector": "医药"},
    {"code": "000071", "name": "华夏恒生ETF联接A", "type": "指数型", "sector": "港股"},
    {"code": "000216", "name": "华安黄金易ETF联接A", "type": "指数型", "sector": "黄金"},
]


class TestFilterFundsIndexTag:
    def test_items_carry_index_tag(self, monkeypatch):
        monkeypatch.setattr(fund_filter, "load_fund_universe", lambda force_refresh=False: _UNIVERSE)
        result = fund_filter.filter_funds(limit=50)
        assert result.ok
        tags = {f.code: f.index_tag for f in result.funds}
        assert tags == {
            "000001": "",
            "000051": "broad",
            "000059": "sector",
            "000071": "broad",
            "000216": "sector",
        }

    def test_index_tag_survives_metrics_enrichment(self, monkeypatch):
        """指标增强只改 scale/returns/risk，不得丢失 index_tag。"""
        monkeypatch.setattr(fund_filter, "load_fund_universe", lambda force_refresh=False: _UNIVERSE)
        monkeypatch.setattr(fund_filter, "_enrich_with_metrics", lambda items: None)
        result = fund_filter.filter_funds(limit=50, with_metrics=True)
        assert result.funds[1].index_tag == "broad"
