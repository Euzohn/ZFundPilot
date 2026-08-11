"""基金分红数据抓取与检测。"""
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import analysis, db
from .models import ACTION_DIVIDEND, ACTION_REINVEST

logger = logging.getLogger(__name__)

# 按基金缓存分红历史，TTL 6 小时（日内不变）
_DIV_CACHE: dict[str, dict] = {}
_DIV_CACHE_TTL = 6 * 3600

# 检测窗口：最近 N 天的分红事件
_LOOKBACK_DAYS = 90

# 并行抓取的线程数
_MAX_WORKERS = 3


def _match_col(columns, candidates) -> str | None:
    """在 DataFrame 列中模糊匹配候选名。"""
    cols = list(columns)
    for cand in candidates:
        for c in cols:
            if cand in str(c).lower() or cand in str(c):
                return c
    return None


@dataclass
class DividendEvent:
    """单条分红事件。"""
    fund_code: str
    fund_name: str
    record_date: str       # 权益登记日
    ex_date: str           # 除息日
    per_share: float       # 每份分红(元/份)
    pay_date: str          # 分红发放日
    held_shares: float = 0.0       # 当前持仓份额
    estimated_amount: float = 0.0  # 预估分红金额 = held_shares × per_share
    dividend_method: str = "cash"  # 基金的默认分红方式
    already_recorded: bool = False  # 是否已有对应交易


def _fetch_fund_dividends(fund_code: str) -> list[dict]:
    """获取单只基金的完整分红历史（带缓存）。失败返回空列表。"""
    now = time.time()
    cached = _DIV_CACHE.get(fund_code)
    if cached and now - cached["ts"] < _DIV_CACHE_TTL:
        return cached["data"]

    try:
        import akshare as ak
        df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="分红送配详情")
        if df is None or df.empty:
            return []
        records = df.to_dict("records")
        _DIV_CACHE[fund_code] = {"ts": now, "data": records}
        return records
    except Exception as e:
        msg = str(e)
        if "no text parsed" in msg or "No tables found" in msg:
            logger.debug("[fetch_dividend] %s 无分红记录（空响应）", fund_code)
        else:
            logger.warning("[fetch_dividend] 获取 %s 分红数据失败: %s", fund_code, e)
        if cached:
            return cached["data"]
        return []


def _parse_per_share(raw) -> float | None:
    """从分红金额字段解析每股分红(元/份)。

    AkShare 返回格式如 "每10份派现金0.0500元"，需提取 0.0500 并 /10。
    fund_fh_em 接口可能返回纯 float 如 0.0100，直接使用。
    """
    if isinstance(raw, (int, float)):
        v = float(raw)
        return v if v > 0 else None
    s = str(raw).strip()
    m = re.search(r"现金(\d+\.?\d*)\s*元", s)
    if not m:
        m = re.search(r"(\d+\.?\d+)\s*元", s)
    if m:
        amount = float(m.group(1))
        if "10" in s[:5]:
            amount /= 10
        return amount if amount > 0 else None
    # fallback: 纯数字字符串
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return None


def _parse_dividend_row(row: dict, fund_code: str, fund_name: str) -> DividendEvent | None:
    """解析单行分红数据为 DividendEvent。列名模糊匹配。"""
    col_record = _match_col(row.keys(), ["权益登记日", "登记日"])
    col_ex = _match_col(row.keys(), ["除息日", "除息日期"])
    col_per = _match_col(row.keys(), ["每10份分红", "每份分红", "分红"])
    col_pay = _match_col(row.keys(), ["分红发放日", "发放日"])
    if not col_ex or not col_per:
        return None
    per_share = _parse_per_share(row.get(col_per, 0))
    if not per_share:
        return None
    return DividendEvent(
        fund_code=fund_code,
        fund_name=fund_name,
        record_date=str(row.get(col_record, "")).strip()[:10],
        ex_date=str(row.get(col_ex, "")).strip()[:10],
        per_share=per_share,
        pay_date=str(row.get(col_pay, "")).strip()[:10],
    )


def _date_close(d1: str, d2: str, tolerance: int = 3) -> bool:
    """判断两个日期字符串是否在 tolerance 天内。"""
    try:
        date1 = datetime.strptime(d1[:10], "%Y-%m-%d")
        date2 = datetime.strptime(d2[:10], "%Y-%m-%d")
        return abs((date1 - date2).days) <= tolerance
    except (ValueError, TypeError):
        return False


def check_dividends() -> list[DividendEvent]:
    """检查持仓基金的分红事件，返回未记录的分红列表。

    1. 获取当前持仓（所有 is_open 的基金）
    2. 并行抓取每只持仓基金的分红历史
    3. 过滤最近 _LOOKBACK_DAYS 天的事件
    4. 查已有 dividend/reinvest 交易做去重
    5. 按基金 dividend_method 预选 action
    """
    positions = analysis.calculate_positions()
    held = {p.fund_code: p for p in positions if p.is_open}
    if not held:
        return []

    funds = {f.fund_code: f for f in db.get_funds()}

    all_events: list[DividendEvent] = []
    cutoff = (datetime.now() - timedelta(days=_LOOKBACK_DAYS)).strftime("%Y-%m-%d")

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        future_map = {
            pool.submit(_fetch_fund_dividends, code): code
            for code in held
        }
        for future in as_completed(future_map):
            code = future_map[future]
            pos = held[code]
            fund = funds.get(code)
            fund_name = fund.fund_name if fund else code
            method = fund.dividend_method if fund else "cash"
            try:
                rows = future.result()
            except Exception:
                continue
            for row in rows:
                ev = _parse_dividend_row(row, code, fund_name)
                if not ev or not ev.ex_date:
                    continue
                if ev.ex_date < cutoff:
                    continue
                ev.held_shares = pos.held_shares
                ev.estimated_amount = round(pos.held_shares * ev.per_share, 2)
                ev.dividend_method = method
                all_events.append(ev)

    if not all_events:
        return []

    existing_txs = db.get_transactions()
    for ev in all_events:
        for tx in existing_txs:
            if tx.fund_code != ev.fund_code:
                continue
            if tx.action not in (ACTION_DIVIDEND, ACTION_REINVEST):
                continue
            if _date_close(tx.date, ev.ex_date, tolerance=3):
                ev.already_recorded = True
                break

    return [ev for ev in all_events if not ev.already_recorded]
