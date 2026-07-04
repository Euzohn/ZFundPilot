"""交易流水 CSV 导入 / 导出模块。

CSV 列（表头，第一行）：
    fund_code, action, date, amount, shares, nav, fee, channel, note

- action: buy/卖出/买入/sell 均可识别
- amount / shares / nav：给出任意两个即可，导入时自动补全
- channel：购买渠道（支付宝/理财通等）
支持中文表头。
"""

from __future__ import annotations

import io

import pandas as pd

from .models import ACTION_BUY, ACTION_SELL, Transaction

# 标准列顺序
CSV_COLUMNS = [
    "fund_code", "action", "date", "amount", "shares", "nav",
    "fee", "channel", "note",
]

COLUMN_ALIASES = {
    "基金代码": "fund_code", "代码": "fund_code",
    "操作": "action", "方向": "action", "类型": "action", "买卖": "action",
    "日期": "date", "成交日期": "date", "交易日期": "date",
    "金额": "amount", "成交金额": "amount", "买入金额": "amount",
    "份额": "shares", "成交份额": "shares",
    "净值": "nav", "成交净值": "nav", "单位净值": "nav",
    "手续费": "fee", "费用": "fee",
    "渠道": "channel", "平台": "channel", "购买渠道": "channel",
    "备注": "note",
}

# 操作方向识别
_ACTION_MAP = {
    "buy": ACTION_BUY, "买入": ACTION_BUY, "买": ACTION_BUY,
    "申购": ACTION_BUY, "定投": ACTION_BUY, "b": ACTION_BUY,
    "sell": ACTION_SELL, "卖出": ACTION_SELL, "卖": ACTION_SELL,
    "赎回": ACTION_SELL, "s": ACTION_SELL,
}


def build_template_dataframe() -> pd.DataFrame:
    """带示例的交易流水模板。"""
    samples = [
        {"fund_code": "011612", "action": "买入", "date": "2025-01-02",
         "amount": 1000, "shares": "", "nav": 1.5000, "fee": 0,
         "channel": "支付宝", "note": "定投"},
        {"fund_code": "011612", "action": "买入", "date": "2025-02-08",
         "amount": 1000, "shares": "", "nav": 1.4200, "fee": 0,
         "channel": "支付宝", "note": "加仓"},
        {"fund_code": "011612", "action": "卖出", "date": "2025-06-10",
         "amount": "", "shares": 500, "nav": 1.6000, "fee": 0,
         "channel": "支付宝", "note": "止盈一部分"},
        {"fund_code": "270042", "action": "买入", "date": "2025-03-01",
         "amount": 2000, "shares": "", "nav": 8.0000, "fee": 0,
         "channel": "理财通", "note": ""},
    ]
    return pd.DataFrame(samples, columns=CSV_COLUMNS)


def template_csv_bytes() -> bytes:
    return build_template_dataframe().to_csv(index=False).encode("utf-8-sig")


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    renamed = {}
    for col in df.columns:
        key = str(col).strip()
        if key in CSV_COLUMNS:
            renamed[col] = key
        elif key in COLUMN_ALIASES:
            renamed[col] = COLUMN_ALIASES[key]
    return df.rename(columns=renamed)


def _to_float(value):
    if value is None:
        return None
    s = str(value).strip().replace(",", "").replace("%", "")
    if s == "" or s.lower() == "nan":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _clean_str(value):
    if value is None:
        return ""
    s = str(value).strip()
    return "" if s.lower() == "nan" else s


def _parse_action(value) -> str | None:
    s = str(value).strip().lower()
    return _ACTION_MAP.get(s)


def parse_transactions_csv(source: bytes | str | io.BytesIO) -> tuple[list[Transaction], list[str]]:
    """解析交易流水 CSV，返回 (transactions, 错误信息)。"""
    errors: list[str] = []

    if isinstance(source, (bytes, bytearray)):
        buf = io.BytesIO(source)
        df = None
        for enc in ("utf-8-sig", "utf-8", "gbk"):
            try:
                buf.seek(0)
                df = pd.read_csv(buf, dtype=str, encoding=enc)
                break
            except Exception:  # noqa: BLE001
                continue
        if df is None:
            return [], ["无法解析 CSV 文件编码，请另存为 UTF-8 或 GBK。"]
    else:
        df = pd.read_csv(source, dtype=str)

    df = _normalize_columns(df)

    required = {"fund_code", "action", "date"}
    if not required.issubset(df.columns):
        return [], [
            "缺少必要列：至少需要 fund_code（基金代码）、action（买入/卖出）、date（日期）。"
        ]

    transactions: list[Transaction] = []
    for idx, row in df.iterrows():
        line = int(idx) + 2
        code = _clean_str(row.get("fund_code"))
        if not code:
            errors.append(f"第 {line} 行：基金代码为空，已跳过。")
            continue

        action = _parse_action(row.get("action"))
        if action is None:
            errors.append(f"第 {line} 行（{code}）：无法识别操作方向，已跳过。")
            continue

        date = _clean_str(row.get("date"))
        if not date:
            errors.append(f"第 {line} 行（{code}）：日期为空，已跳过。")
            continue

        amount = _to_float(row.get("amount"))
        shares = _to_float(row.get("shares"))
        nav = _to_float(row.get("nav"))

        tx = Transaction(
            fund_code=code, action=action, date=date,
            amount=amount, shares=shares, nav=nav,
            fee=_to_float(row.get("fee")) or 0.0,
            channel=_clean_str(row.get("channel")),
            note=_clean_str(row.get("note")),
        )
        tx.normalize()

        if not tx.is_valid():
            errors.append(
                f"第 {line} 行（{code}）：金额/份额/净值信息不足，"
                f"至少需要其中两项，已跳过。")
            continue
        transactions.append(tx)

    if not transactions and not errors:
        errors.append("CSV 中没有可导入的交易记录。")
    return transactions, errors


def transactions_to_csv_bytes(transactions: list[Transaction]) -> bytes:
    """导出交易流水为 CSV。"""
    rows = []
    for t in transactions:
        d = t.to_dict()
        rows.append({c: d.get(c, "") for c in CSV_COLUMNS})
    df = pd.DataFrame(rows, columns=CSV_COLUMNS)
    return df.to_csv(index=False).encode("utf-8-sig")
