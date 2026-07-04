"""基金净值获取模块。

数据源优先级：
1. AkShare（ak.fund_open_fund_info_em）
2. 天天基金 pingzhongdata 接口（兜底，仅取近段历史）

对外主要函数：
- fetch_fund_meta(fund_code)        仅获取基金名称/类型（录入时自动补全用）
- fetch_nav_history(fund_code)      获取单只基金历史净值
- update_fund_nav(fund_code)        拉取并写入数据库，返回写入条数
- update_all_holdings_nav()         更新所有持仓基金

设计原则：网络/解析失败不抛出到上层，返回空或 0，并给出可读的错误信息，
以免 Streamlit 页面因单只基金异常整体崩溃。
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from . import config, db
from .models import NavPoint

# 天天基金类型 -> 系统标准资产类型（config.FUND_TYPES）的映射
_TYPE_KEYWORD_MAP = [
    ("QDII", "QDII"),
    ("债券", "债券型"),
    ("指数", "指数型"),
    ("ETF", "指数型"),
    ("联接", "指数型"),
    ("股票", "股票型"),
    ("混合", "混合型"),
    ("货币", "其它"),
    ("FOF", "混合型"),
]

# 基金名称关键词 -> 板块的映射
_SECTOR_KEYWORD_MAP = [
    ("半导体", "半导体材料设备"), ("新材料", "半导体材料设备"),
    ("人工智能", "人工智能"), ("AI应用", "AI应用"), ("AI", "人工智能"),
    ("纳斯达克100", "纳指"), ("纳斯达克", "纳指"), ("纳指", "纳指"),
    ("通信", "通信"), ("5G", "通信"),
    ("有色金属", "有色金属"),
    ("稀土", "稀土永磁"), ("稀有金属", "稀土永磁"),
    ("机器人", "机器人"),
    ("标普500", "标普"), ("标普", "标普"), ("500等权重", "标普"),
    ("金融科技", "大科技"), ("科技领先", "CPO"),
    ("科创创业50", "双创50"), ("科创50", "双创50"), ("双创", "双创50"),
    ("科创", "半导体材料设备"),
    ("海外", "海外基金"), ("全球", "海外基金"), ("QDII", "海外基金"), ("美股", "海外基金"),
    ("PCB", "PCB"),
    ("算力", "国产算力"), ("数字经济", "国产算力"),
    ("商用卫星", "商业航天"), ("卫星通信", "通信"), ("卫星", "商业航天"), ("商业航天", "商业航天"),
    ("体育文化", "其它"),
    ("高端装备", "其它"),
    ("先进制造", "其它"),
    ("债券", "其它"),
    ("电网设备", "其它"),
    ("电子信息", "CPO"), ("集成电路", "CPO"), ("电子", "CPO"),
    ("互联网", "海外基金"),
]

_SECTOR_MAP_PATH = os.path.join(config.DATA_DIR, "sector_map.json")

_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://fund.eastmoney.com/",
}


@dataclass
class FetchResult:
    """单只基金的抓取结果。"""
    fund_code: str
    ok: bool
    written: int = 0
    message: str = ""
    latest_date: str | None = None
    latest_nav: float | None = None


@dataclass
class FundMeta:
    """基金基础信息（名称/类型/板块）。"""
    fund_code: str
    fund_name: str = ""
    fund_type: str = "其它"
    sector: str = ""
    ok: bool = False
    message: str = ""


def _http_get(url: str, timeout: int = 15) -> str:
    """统一 HTTP GET，返回文本。失败抛异常。"""
    req = urllib.request.Request(url, headers=_HTTP_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def _guess_fund_type(raw_type: str, fund_name: str = "") -> str:
    """根据天天基金类型文本或基金名称推断标准资产类型。"""
    text = f"{raw_type} {fund_name}"
    for keyword, mapped in _TYPE_KEYWORD_MAP:
        if keyword in text:
            return mapped
    return "其它"


# ---------------------------------------------------------------------------
# 板块推断
# ---------------------------------------------------------------------------
def _load_sector_map() -> dict[str, str]:
    """加载 fund_code → sector 的精确映射表。"""
    if os.path.exists(_SECTOR_MAP_PATH):
        try:
            with open(_SECTOR_MAP_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: BLE001
            pass
    return {}


def _save_sector_map(mapping: dict[str, str]) -> None:
    """保存精确映射表到文件。"""
    os.makedirs(os.path.dirname(_SECTOR_MAP_PATH), exist_ok=True)
    with open(_SECTOR_MAP_PATH, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)


def _guess_sector(fund_name: str) -> str:
    """通过基金名称关键词推断所属板块。"""
    for keyword, sector in _SECTOR_KEYWORD_MAP:
        if keyword in fund_name:
            return sector
    return "其它"


def save_sector_mapping(fund_code: str, sector: str) -> None:
    """写入一条 fund_code → sector 映射（供 UI 保存时调用）。

    若 sector 为空白或 "其它"，删除已有的映射记录。
    """
    mapping = _load_sector_map()
    effective = sector.strip()
    if effective and effective != "其它":
        mapping[fund_code] = effective
    elif fund_code in mapping:
        del mapping[fund_code]
    else:
        return
    _save_sector_map(mapping)


# ---------------------------------------------------------------------------
# 基金基础信息（名称 / 类型）
# ---------------------------------------------------------------------------
def fetch_fund_meta(fund_code: str) -> FundMeta:
    """通过基金代码获取名称、类型与板块。不抛异常。

    数据源：
    - 名称：天天基金 pingzhongdata（fS_name 字段）
    - 类型：名称关键词推断
    - 板块：优先 sector_map.json 精确映射，无则名称关键词推断
    """
    fund_code = fund_code.strip()
    if not fund_code:
        return FundMeta(fund_code, ok=False, message="基金代码为空")

    try:
        txt = _http_get(f"https://fund.eastmoney.com/pingzhongdata/{fund_code}.js")
    except Exception as exc:  # noqa: BLE001
        return FundMeta(fund_code, ok=False, message=f"网络请求失败：{exc}")

    m_name = re.search(r'fS_name\s*=\s*"([^"]*)"', txt)
    if not m_name or not m_name.group(1):
        return FundMeta(fund_code, ok=False, message="未找到该基金，请检查代码")

    name = m_name.group(1)
    fund_type = _guess_fund_type("", name)

    sector = _load_sector_map().get(fund_code)
    if not sector:
        sector = _guess_sector(name)

    return FundMeta(fund_code=fund_code, fund_name=name,
                    fund_type=fund_type, sector=sector,
                    ok=True, message="成功")


# ---------------------------------------------------------------------------
# 数据源 1：AkShare
# ---------------------------------------------------------------------------
def _fetch_via_akshare(fund_code: str) -> list[NavPoint]:
    """使用 AkShare 获取单位净值走势。失败抛异常。"""
    import akshare as ak  # 延迟导入，未安装时不影响其它功能

    df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
    if df is None or df.empty:
        raise ValueError("AkShare 返回空数据")

    # 列名通常为：净值日期 / 单位净值 / 日增长率
    col_date = _match_col(df.columns, ["净值日期", "日期", "date"])
    col_nav = _match_col(df.columns, ["单位净值", "nav"])
    if not col_date or not col_nav:
        raise ValueError(f"无法识别列名：{list(df.columns)}")

    points: list[NavPoint] = []
    for _, row in df.iterrows():
        d = str(row[col_date])[:10]
        try:
            nav = float(row[col_nav])
        except (TypeError, ValueError):
            continue
        points.append(NavPoint(fund_code=fund_code, date=d, nav=nav,
                               source="akshare"))
    return points


def _match_col(columns, candidates) -> str | None:
    """在 DataFrame 列中模糊匹配候选名。"""
    cols = list(columns)
    for cand in candidates:
        for c in cols:
            if cand in str(c).lower() or cand in str(c):
                return c
    return None


# ---------------------------------------------------------------------------
# 数据源 2：天天基金（兜底）
# ---------------------------------------------------------------------------
def _fetch_via_eastmoney(fund_code: str) -> list[NavPoint]:
    """从天天基金 pingzhongdata 拉取历史净值。失败抛异常。"""
    text = _http_get(f"https://fund.eastmoney.com/pingzhongdata/{fund_code}.js")

    # 提取 Data_netWorthTrend = [{x:时间戳, y:净值}, ...]
    m = re.search(r"Data_netWorthTrend\s*=\s*(\[.*?\]);", text)
    if not m:
        raise ValueError("未找到净值数据段")
    arr = json.loads(m.group(1))

    points: list[NavPoint] = []
    for item in arr:
        ts = item.get("x")
        nav = item.get("y")
        if ts is None or nav is None:
            continue
        d = time.strftime("%Y-%m-%d", time.localtime(ts / 1000))
        points.append(NavPoint(fund_code=fund_code, date=d, nav=float(nav),
                               source="eastmoney"))
    return points


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------
def fetch_nav_history(fund_code: str) -> list[NavPoint]:
    """获取历史净值，AkShare 优先，失败自动切换天天基金。"""
    fund_code = fund_code.strip()
    errors: list[str] = []

    for attempt in range(config.FETCH_MAX_RETRIES):
        try:
            points = _fetch_via_akshare(fund_code)
            if points:
                return points
        except Exception as exc:  # noqa: BLE001
            errors.append(f"akshare#{attempt + 1}: {exc}")
            time.sleep(0.5)

    # 兜底
    try:
        points = _fetch_via_eastmoney(fund_code)
        if points:
            return points
    except Exception as exc:  # noqa: BLE001
        errors.append(f"eastmoney: {exc}")

    raise RuntimeError("；".join(errors) or "未知错误")


def update_fund_nav(fund_code: str) -> FetchResult:
    """拉取并写入单只基金净值。不抛异常。"""
    try:
        points = fetch_nav_history(fund_code)
    except Exception as exc:  # noqa: BLE001
        return FetchResult(fund_code, ok=False, message=str(exc))

    written = db.upsert_nav_batch(points)
    latest = max(points, key=lambda p: p.date)
    return FetchResult(
        fund_code=fund_code,
        ok=True,
        written=written,
        message="成功",
        latest_date=latest.date,
        latest_nav=latest.nav,
    )


def update_all_holdings_nav(
    progress: Callable[[int, int, str], None] | None = None,
) -> list[FetchResult]:
    """更新所有持仓基金的净值。

    progress: 可选回调 (当前序号, 总数, 基金代码)，供 Streamlit 显示进度。
    """
    codes = db.get_distinct_fund_codes()
    results: list[FetchResult] = []
    total = len(codes)
    for i, code in enumerate(codes, start=1):
        if progress:
            progress(i, total, code)
        results.append(update_fund_nav(code))
        time.sleep(0.3)  # 轻微限速，避免被数据源限流
    return results


if __name__ == "__main__":
    import sys

    db.init_db()
    code = sys.argv[1] if len(sys.argv) > 1 else "013093"
    print(f"抓取基金 {code} ...")
    res = update_fund_nav(code)
    print(res)
