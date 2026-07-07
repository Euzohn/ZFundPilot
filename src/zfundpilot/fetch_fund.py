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
# 注意：按顺序匹配，越具体越靠前
_TYPE_KEYWORD_MAP = [
    ("QDII", "QDII"),
    ("FOF", "混合型"),
    ("REIT", "其它"),

    ("ETF联接", "指数型"),
    ("ETF", "指数型"),
    ("LOF", "指数型"),
    ("指数增强", "指数型"),
    ("指数", "指数型"),
    ("联接", "指数型"),

    ("股票", "股票型"),
    ("混合", "混合型"),
    ("债券", "债券型"),

    ("货币", "其它"),
    ("现金", "其它"),
    ("理财", "其它"),
]

# 基金名称关键词 -> 板块映射
# 按顺序匹配，长关键词优先

_SECTOR_KEYWORD_MAP = [

    # ================= AI =================
    ("AI应用", "AI应用"),
    ("AI算力", "国产算力"),
    ("人工智能", "人工智能"),
    ("AIGC", "人工智能"),
    ("ChatGPT", "人工智能"),
    ("AI", "人工智能"),

    # ================= 半导体 =================
    ("半导体设备", "半导体材料设备"),
    ("半导体材料", "半导体材料设备"),
    ("半导体", "半导体材料设备"),
    ("芯片", "半导体"),
    ("集成电路", "半导体"),
    ("EDA", "半导体"),
    ("存储芯片", "半导体"),

    # ================= 算力 =================
    ("算力", "国产算力"),
    ("智算", "国产算力"),
    ("东数西算", "国产算力"),

    # ================= 通信 =================
    ("卫星通信", "通信"),
    ("通信设备", "通信"),
    ("通信", "通信"),
    ("光通信", "通信"),
    ("光模块", "通信"),
    ("CPO", "通信"),
    ("6G", "通信"),
    ("5G", "通信"),

    # ================= 商业航天 =================
    ("商业航天", "商业航天"),
    ("商用卫星", "商业航天"),
    ("低空经济", "商业航天"),
    ("卫星互联网", "商业航天"),
    ("卫星", "商业航天"),

    # ================= 机器人 =================
    ("人形机器人", "机器人"),
    ("机器人", "机器人"),

    # ================= PCB =================
    ("PCB", "PCB"),
    ("覆铜板", "PCB"),

    # ================= 科技 =================
    ("金融科技", "大科技"),
    ("恒生科技", "港股科技"),
    ("科技领先", "科技"),
    ("科技", "科技"),
    ("科创创业50", "双创50"),
    ("科创50", "双创50"),
    ("双创", "双创50"),

    # ================= 信息技术 =================
    ("电子信息", "信息技术"),
    ("软件", "信息技术"),
    ("信创", "信息技术"),
    ("云计算", "信息技术"),
    ("数据要素", "信息技术"),
    ("数据中心", "信息技术"),
    ("数字经济", "信息技术"),

    # ================= 电子 =================
    ("消费电子", "电子"),
    ("电子", "电子"),

    # ================= 有色 =================
    ("稀有金属", "稀土永磁"),
    ("稀土永磁", "稀土永磁"),
    ("稀土", "稀土永磁"),
    ("有色金属", "有色金属"),

    # ================= 新能源 =================
    ("新能源车", "新能源"),
    ("新能源汽车", "新能源"),
    ("锂电", "新能源"),
    ("锂电池", "新能源"),
    ("储能", "新能源"),
    ("光伏", "新能源"),
    ("风电", "新能源"),
    ("新能源", "新能源"),

    # ================= 医药 =================
    ("创新药", "创新药"),
    ("CXO", "创新药"),
    ("生物医药", "医药"),
    ("医疗器械", "医药"),
    ("医疗", "医药"),
    ("医药", "医药"),

    # ================= 金融 =================
    ("证券", "证券"),
    ("券商", "证券"),
    ("银行", "银行"),
    ("保险", "保险"),

    # ================= 消费 =================
    ("食品饮料", "消费"),
    ("白酒", "消费"),
    ("消费", "消费"),

    # ================= 周期 =================
    ("煤炭", "煤炭"),
    ("钢铁", "钢铁"),
    ("黄金", "黄金"),

    # ================= 制造 =================
    ("高端装备", "高端装备"),
    ("先进制造", "先进制造"),
    ("电网设备", "电力设备"),

    # ================= 海外 =================
    ("纳斯达克100", "纳指"),
    ("纳斯达克", "纳指"),
    ("纳指", "纳指"),

    ("标普500", "标普"),
    ("500等权重", "标普"),
    ("标普", "标普"),

    ("恒生互联网", "港股科技"),
    ("恒生", "港股"),
    ("港股", "港股"),

    ("美股", "海外基金"),
    ("海外", "海外基金"),
    ("QDII", "海外基金"),

    # ================= 宽基指数 =================
    ("沪深300", "沪深300"),
    ("中证500", "中证500"),
    ("中证1000", "中证1000"),
    ("创业板", "创业板"),
    ("创业50", "创业板"),
    ("北证50", "北证50"),

    # ================= 军工 =================
    ("军工", "军工"),
    ("国防", "军工"),

    # ================= 地产 =================
    ("房地产", "房地产"),
    ("地产", "房地产"),

    # ================= 化工 =================
    ("化工", "化工"),

    # ================= 传媒 =================
    ("传媒", "传媒"),
    ("游戏", "传媒"),
    ("影视", "传媒"),

    # ================= 农业 =================
    ("农业", "农业"),

    # ================= 环保 =================
    ("环保", "环保"),
    ("碳中和", "环保"),
    ("低碳", "环保"),

    # ================= 电力 =================
    ("电力", "电力"),

    # ================= 建筑建材 =================
    ("建筑", "建筑建材"),
    ("建材", "建筑建材"),

    # ================= 交运物流 =================
    ("交通运输", "交运物流"),
    ("物流", "交运物流"),

    # ================= 石油石化 =================
    ("石油", "石油石化"),
    ("石化", "石油石化"),

    # ================= 旅游 =================
    ("旅游", "旅游"),
    ("酒店", "旅游"),

    # ================= 其它 =================
    ("债券", "其它"),
    ("体育文化", "其它"),
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
    """根据天天基金类型文本或基金名称推断标准资产类型。

    合并用户自定义 + 默认类型关键词，自定义排前面优先匹配。
    """
    text = f"{raw_type} {fund_name}"
    merged = _load_custom_keywords("type_keywords_custom") + _TYPE_KEYWORD_MAP
    for keyword, mapped in merged:
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


def _load_custom_keywords(key: str) -> list[tuple[str, str]]:
    """从数据库读取用户自定义关键词映射（JSON 数组 → 元组列表）。"""
    raw = db.get_preference(key)
    if not raw:
        return []
    try:
        arr = json.loads(raw)
        return [(item["keyword"], item["mapped"]) for item in arr if "keyword" in item and "mapped" in item]
    except Exception:  # noqa: BLE001
        return []


def _guess_sector(fund_name: str) -> str:
    """通过基金名称关键词推断所属板块。

    合并用户自定义 + 默认板块关键词，自定义排前面优先匹配。
    """
    merged = _load_custom_keywords("sector_keywords_custom") + _SECTOR_KEYWORD_MAP
    for keyword, sector in merged:
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
# 关键词映射导出（供 API / 前端展示）
# ---------------------------------------------------------------------------

def get_available_types() -> list[str]:
    """返回所有可用资产类型（去重排序）。"""
    seen = set()
    for _, mapped in _TYPE_KEYWORD_MAP:
        seen.add(mapped)
    custom = _load_custom_keywords("type_keywords_custom")
    for _, mapped in custom:
        seen.add(mapped)
    return sorted(seen)


def get_available_sectors() -> list[str]:
    """返回所有可用板块（去重排序）。"""
    seen = set()
    for _, mapped in _SECTOR_KEYWORD_MAP:
        seen.add(mapped)
    custom = _load_custom_keywords("sector_keywords_custom")
    for _, mapped in custom:
        seen.add(mapped)
    return sorted(seen)


def get_keyword_maps() -> dict:
    """返回结构化关键词映射（默认 + 自定义），供 API 使用。"""
    type_custom = _load_custom_keywords("type_keywords_custom")
    sector_custom = _load_custom_keywords("sector_keywords_custom")
    return {
        "type_defaults": [{"keyword": k, "mapped": v} for k, v in _TYPE_KEYWORD_MAP],
        "sector_defaults": [{"keyword": k, "mapped": v} for k, v in _SECTOR_KEYWORD_MAP],
        "type_custom": [{"keyword": k, "mapped": v} for k, v in type_custom],
        "sector_custom": [{"keyword": k, "mapped": v} for k, v in sector_custom],
        "available_types": get_available_types(),
        "available_sectors": get_available_sectors(),
    }


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
    """更新所有基金的净值（从 funds 表取，不依赖 transactions）。

    progress: 可选回调 (当前序号, 总数, 基金代码)，供 UI 显示进度。
    """
    funds = db.get_funds()
    results: list[FetchResult] = []
    total = len(funds)
    for i, f in enumerate(funds, start=1):
        if progress:
            progress(i, total, f.fund_code)
        results.append(update_fund_nav(f.fund_code))
        time.sleep(0.3)  # 轻微限速，避免被数据源限流
    return results


# ---------------------------------------------------------------------------
# 费率查询（申购费率 / 赎回费率）
# ---------------------------------------------------------------------------

_fee_cache: dict[str, dict] = {}
_FEE_CACHE_TTL = 3600  # 1 小时


@dataclass
class PurchaseTier:
    min_amount: float = 0
    max_amount: float | None = None  # None 表示无穷大（'X <= 金额'）
    rate: float = 0.0                # 小数，如 0.0015 表示 0.15%
    is_fixed: bool = False           # True 表示固定费用（如 1000元/笔）
    fixed_fee: float = 0.0           # 固定费用金额
    label: str = ""                  # 原始描述


@dataclass
class RedemptionTier:
    min_days: int = 0
    max_days: int | None = None     # None 表示无穷大
    rate: float = 0.0               # 小数


@dataclass
class FeeRates:
    fund_code: str
    purchase: list[PurchaseTier] = None
    redemption: list[RedemptionTier] = None
    management_fee: float | None = None   # 管理费（年化）
    custodian_fee: float | None = None    # 托管费（年化）
    sales_fee: float | None = None        # 销售服务费（年化）
    ok: bool = False
    message: str = ""


@dataclass
class FeeLot:
    """FIFO 赎回批次明细。"""
    buy_date: str
    buy_shares: float
    used_shares: float
    days_held: int
    rate: float
    fee: float
    nav: float = 0.0


@dataclass
class CalcFeeResult:
    fee: float = 0.0
    rate: float = 0.0
    label: str = ""
    lots: list[dict] | None = None  # 仅卖出时有批次明细


def _parse_pct(text: str) -> float:
    """解析百分比字符串，如 '1.50%' → 0.015。"""
    text = text.strip().replace(",", "").replace("，", "")
    if text.endswith("%"):
        return float(text[:-1].strip()) / 100
    return 0.0


def _parse_fixed_fee(text: str) -> float | None:
    """解析固定手续费，如 '1000元/笔' → 1000.0。"""
    m = re.search(r"([\d,.]+)\s*元", text)
    if m:
        return float(m.group(1).replace(",", ""))
    return None


def _parse_amount_range(text: str) -> tuple[float, float | None]:
    """解析金额范围如 '0 <= 金额 < 100万' 或 '小于100万元' → (0, 1_000_000)。返回 (min, max)。"""
    text = text.strip()

    def _to_val(t: str) -> float:
        yi = re.search(r"([\d.]+)\s*亿", t)
        wan = re.search(r"([\d.]+)\s*万", t)
        num = re.search(r"([\d.]+)", t)
        if yi:
            return float(yi.group(1)) * 100_000_000
        if wan:
            return float(wan.group(1)) * 10_000
        if num:
            return float(num.group(1))
        return 0

    # "大于等于X,小于Y" (必须在前，防止'小于'先匹配到后半段)
    m = re.search(r"大于等于\s*([\d.]+)\s*(亿|万|元)?", text)
    if m:
        min_v = _to_val(m.group(0))
        m2 = re.search(r"小于\s*([\d.]+)\s*(亿|万|元)?", text)
        if m2:
            max_v = _to_val(m2.group(0))
            return (min_v, max_v)
        return (min_v, None)

    # "小于X万元" / "小于X元"
    m = re.search(r"小于\s*([\d.]+)\s*(亿|万|元)?", text)
    if m:
        return (0, _to_val(m.group(0)))

    # "X <= 金额 < Y"
    m = re.search(r"([\d.]+)\s*(亿|万)?\s*<\s*=\s*金额\s*<\s*([\d.]+)\s*(亿|万)?", text)
    if m:
        min_v = _to_val(f"{m.group(1)}{m.group(2) or ''}")
        max_v = _to_val(f"{m.group(3)}{m.group(4) or ''}")
        return (min_v, max_v)

    # "金额 < X"
    m = re.search(r"金额\s*<\s*([\d.]+)\s*(亿|万|元)?", text)
    if m:
        return (0, _to_val(m.group(0)))

    # "金额 >= X"
    m = re.search(r"金额\s*>=\s*([\d.]+)\s*(亿|万|元)?", text)
    if m:
        return (_to_val(m.group(0)), None)

    return (0, None)


def _parse_holding_period(text: str) -> tuple[int, int | None]:
    """解析持有期限如 '小于7天' → (0, 6)，'大于等于7天' → (7, None)。"""
    text = text.strip()

    # "小于X天"
    m = re.search(r"小于\s*([\d.]+)\s*天", text)
    if m:
        return (0, int(float(m.group(1))) - 1)

    # "大于等于X天" (单独)
    m = re.search(r"大于等于\s*([\d.]+)\s*天$", text)
    if m:
        return (int(float(m.group(1))), None)

    # "大于等于X天,小于Y天" 或 "大于等于X天，小于Y天"
    m = re.search(r"大于等于\s*([\d.]+)\s*天.*?小于\s*([\d.]+)\s*天", text)
    if m:
        return (int(float(m.group(1))), int(float(m.group(2))) - 1)

    # "大于等于X年,小于Y年" 或 "大于等于X年，小于Y年"
    m = re.search(r"大于等于\s*([\d.]+)\s*年.*?小于\s*([\d.]+)\s*年", text)
    if m:
        return (int(float(m.group(1))) * 365, int(float(m.group(2))) * 365 - 1)

    # "大于等于X年" (单独)
    m = re.search(r"大于等于\s*([\d.]+)\s*年$", text)
    if m:
        return (int(float(m.group(1))) * 365, None)

    return (0, None)


def _fetch_fee_rates_from_akshare(fund_code: str) -> FeeRates:
    """从 AkShare 获取基金费率。失败抛异常。"""
    import akshare as ak

    result = FeeRates(fund_code=fund_code, ok=True, message="成功")

    # 申购费率（前端）
    try:
        df_p = ak.fund_fee_em(symbol=fund_code, indicator="申购费率（前端）")
        if df_p is not None and not df_p.empty:
            result.purchase = _parse_purchase_tiers(df_p)
    except Exception:
        result.purchase = []

    # 赎回费率
    try:
        df_r = ak.fund_fee_em(symbol=fund_code, indicator="赎回费率")
        if df_r is not None and not df_r.empty:
            result.redemption = _parse_redemption_tiers(df_r)
    except Exception:
        result.redemption = []

    # 运作费用
    try:
        df_op = ak.fund_fee_em(symbol=fund_code, indicator="运作费用")
        if df_op is not None and not df_op.empty:
            for _, row in df_op.iterrows():
                for col in df_op.columns:
                    val = str(row[col])
                    if "管理" in str(col) and "%" in val:
                        result.management_fee = _parse_pct(val)
                    elif "托管" in str(col) and "%" in val:
                        result.custodian_fee = _parse_pct(val)
                    elif "销售" in str(col) and "%" in val:
                        result.sales_fee = _parse_pct(val)
    except Exception:
        pass

    return result


def _parse_purchase_tiers(df) -> list[PurchaseTier]:
    """解析申购费率 DataFrame → PurchaseTier 列表。"""
    tiers: list[PurchaseTier] = []

    cols = list(df.columns)
    amount_col = _match_col(cols, ["适用金额", "金额", "档次"])
    if not amount_col:
        return []

    rate_col = _match_col(cols, ["原费率|天天基金优惠费率", "原费率|优惠费率"])
    use_discounted = rate_col is not None
    if not rate_col:
        rate_col = _match_col(cols, ["天天基金优惠费率", "优惠费率", "原费率", "申购费率", "费率"])
    if not rate_col:
        for c in cols:
            if c != amount_col:
                rate_col = c
                break

    for _, row in df.iterrows():
        amount_text = str(row[amount_col]).strip()
        rate_text = str(row[rate_col]).strip()
        if not amount_text or amount_text == "nan":
            continue

        tier = PurchaseTier(label=amount_text)
        min_a, max_a = _parse_amount_range(amount_text)
        tier.min_amount = min_a
        tier.max_amount = max_a

        # 处理 "原费率|天天基金优惠费率" 列
        if use_discounted and "|" in rate_text:
            parts = [p.strip() for p in rate_text.split("|")]
            if len(parts) >= 2:
                rate_text = parts[1]  # 取优惠费率

        # 检查是否为固定费用
        fixed = _parse_fixed_fee(rate_text)
        if fixed is not None:
            tier.is_fixed = True
            tier.fixed_fee = fixed
            tier.rate = 0
        else:
            tier.rate = _parse_pct(rate_text)

        tiers.append(tier)

    return tiers


def _parse_redemption_tiers(df) -> list[RedemptionTier]:
    """解析赎回费率 DataFrame → RedemptionTier 列表。"""
    tiers: list[RedemptionTier] = []
    cols = list(df.columns)
    period_col = _match_col(cols, ["适用期限", "期限", "持有期", "持有期限"])
    rate_col = _match_col(cols, ["赎回费率", "费率"])

    if not period_col or not rate_col:
        return []

    for _, row in df.iterrows():
        period_text = str(row[period_col]).strip()
        rate_text = str(row[rate_col]).strip()
        if not period_text or period_text == "nan":
            continue

        min_d, max_d = _parse_holding_period(period_text)
        tier = RedemptionTier(min_days=min_d, max_days=max_d, rate=_parse_pct(rate_text))
        tiers.append(tier)

    # 按最小天数排序
    tiers.sort(key=lambda t: t.min_days)
    return tiers


def fetch_fund_fee_rates(fund_code: str) -> FeeRates:
    """获取基金费率表（带内存缓存）。不抛异常。"""
    fund_code = fund_code.strip()
    now = time.time()

    cached = _fee_cache.get(fund_code)
    if cached and now - cached["ts"] < _FEE_CACHE_TTL:
        return cached["data"]

    try:
        rates = _fetch_fee_rates_from_akshare(fund_code)
    except Exception as exc:
        rates = FeeRates(fund_code=fund_code, ok=False, message=str(exc))

    _fee_cache[fund_code] = {"ts": now, "data": rates}
    return rates


def calc_purchase_fee(fund_code: str, amount: float) -> CalcFeeResult:
    """计算买入手续费。"""
    rates = fetch_fund_fee_rates(fund_code)
    if not rates.ok or not rates.purchase:
        return CalcFeeResult(fee=0, rate=0, label="费率未知")

    # 按金额匹配分档
    for tier in rates.purchase:
        if amount < tier.min_amount:
            continue
        if tier.max_amount is not None and amount >= tier.max_amount:
            continue
        if tier.is_fixed:
            fee = tier.fixed_fee
            label = tier.label
            return CalcFeeResult(fee=fee, rate=0, label=label)
        fee = round(amount * tier.rate, 2)
        pct = f"{tier.rate * 100:.2f}%"
        label = f"申购费率 {pct}"
        return CalcFeeResult(fee=fee, rate=tier.rate, label=label)

    # 超出最大档：用最后一档
    last = rates.purchase[-1]
    if last.is_fixed:
        return CalcFeeResult(fee=last.fixed_fee, rate=0, label=last.label)
    fee = round(amount * last.rate, 2)
    pct = f"{last.rate * 100:.2f}%"
    return CalcFeeResult(fee=fee, rate=last.rate, label=f"申购费率 {pct}")


def calc_redemption_fee(
    fund_code: str,
    sell_date: str,
    sell_shares: float,
) -> CalcFeeResult:
    """计算赎回手续费（FIFO 先进先出）。"""
    rates = fetch_fund_fee_rates(fund_code)
    if not rates.ok or not rates.redemption:
        return CalcFeeResult(fee=0, rate=0, label="费率未知")

    # 获取该基金所有买入记录（按日期升序）
    buy_txs = db.get_transactions(fund_code)
    buy_lots = [t for t in buy_txs if t.action == "buy" and t.date and t.shares]

    if not buy_lots:
        return CalcFeeResult(fee=0, rate=0, label="无买入记录，无法计算持有期")

    sell_dt = _parse_date(sell_date)
    remaining = sell_shares
    total_fee = 0.0
    lots_detail: list[FeeLot] = []

    for lot in buy_lots:
        if remaining <= 0:
            break
        lot_shares = lot.shares or 0
        lot_nav = lot.nav or 0
        used = min(lot_shares, remaining)
        days = (sell_dt - _parse_date(lot.date)).days
        if days < 0:
            days = 0

        # 按持有天数匹配费率
        rate = 0.0
        for tier in rates.redemption:
            if days >= tier.min_days:
                if tier.max_days is None or days <= tier.max_days:
                    rate = tier.rate
                    break

        lot_amount = used * lot_nav
        fee = round(lot_amount * rate, 2)
        total_fee += fee
        remaining -= used

        lots_detail.append(FeeLot(
            buy_date=lot.date,
            buy_shares=lot_shares,
            used_shares=used,
            days_held=days,
            rate=rate,
            fee=fee,
            nav=lot_nav,
        ))

    # 如果还有剩余份额无法匹配（超出买入总量），按最低费率
    if remaining > 0 and buy_lots:
        lowest_rate = rates.redemption[-1].rate if rates.redemption else 0
        latest = db.get_latest_nav(fund_code)
        extra_nav = float(latest["nav"]) if latest else 1.0
        extra_fee = round(remaining * extra_nav * lowest_rate, 2)
        total_fee += extra_fee
        lots_detail.append(FeeLot(
            buy_date="",
            buy_shares=0,
            used_shares=remaining,
            days_held=0,
            rate=lowest_rate,
            fee=extra_fee,
            nav=extra_nav,
        ))

    total_fee = round(total_fee, 2)

    # 有效费率 = 总费用 / 总卖出金额
    total_sold_amount = sum(l.used_shares * l.nav for l in lots_detail)
    effective_rate = total_fee / total_sold_amount if total_sold_amount > 0 else 0

    label = f"赎回费率 {effective_rate * 100:.2f}%"
    return CalcFeeResult(
        fee=total_fee,
        rate=effective_rate,
        label=label,
        lots=[{"buy_date": l.buy_date, "buy_shares": l.buy_shares,
               "used_shares": l.used_shares, "days_held": l.days_held,
               "rate": l.rate, "fee": l.fee} for l in lots_detail],
    )


def _parse_date(date_str: str):
    """解析 YYYY-MM-DD 字符串为 datetime.date。"""
    import datetime as dt
    parts = date_str.split("-")
    return dt.date(int(parts[0]), int(parts[1]), int(parts[2]))


def clear_fee_cache() -> None:
    """清空费率缓存（调试/测试用）。"""
    _fee_cache.clear()


def get_fee_cache_info() -> int:
    """返回缓存中的基金数量。"""
    return len(_fee_cache)


if __name__ == "__main__":
    import sys

    db.init_db()
    code = sys.argv[1] if len(sys.argv) > 1 else "013093"
    if len(sys.argv) > 2 and sys.argv[2] == "fee":
        print(f"查询费率 {code} ...")
        rates = fetch_fund_fee_rates(code)
        print(f"申购: {rates.purchase}")
        print(f"赎回: {rates.redemption}")
        print(f"管理费: {rates.management_fee}")
        print(f"托管费: {rates.custodian_fee}")
        print(f"销售服务费: {rates.sales_fee}")
        if rates.purchase:
            res = calc_purchase_fee(code, 10000)
            print(f"买入 ¥10000 手续费: {res}")
        if rates.redemption:
            res = calc_redemption_fee(code, "2026-07-07", 100)
            print(f"卖出 100 份手续费: {res}")
    else:
        print(f"抓取基金 {code} ...")
        res = update_fund_nav(code)
        print(res)
