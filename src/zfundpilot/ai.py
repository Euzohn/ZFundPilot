"""AI 投顾模块 — 持仓上下文构建 + 提供商识别 + LLM 流式调用（含联网搜索）。

支持 OpenAI 兼容 API，根据 base_url 自动识别提供商（智谱/Kimi/通义千问），
并启用对应格式的联网搜索（web_search）。
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from . import analysis, config, db, rebalance, risk

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 持仓上下文构建
# ---------------------------------------------------------------------------
def build_portfolio_context() -> str:
    """汇总当前持仓、风险、建议，构建给 LLM 的上下文文本。"""
    try:
        db.init_db()
        summary = analysis.calculate_summary()
        positions = analysis.calculate_positions()
        open_positions = [p for p in positions if p.is_open]
        report = risk.build_risk_report(positions)
        advice = rebalance.generate_advice(positions, report)

        lines = ["## 当前组合概况"]
        lines.append(f"- 持仓成本: {summary.total_cost:,.2f}")
        lines.append(f"- 当前市值: {summary.total_value:,.2f}")
        lines.append(f"- 浮动盈亏: {summary.unrealized_pnl:+,.2f}")
        lines.append(f"- 总收益率: {summary.total_return:+.2%}")
        lines.append(f"- 持仓数量: {summary.holding_count}")

        lines.append("\n## 风险指标")
        if report.max_drawdown is not None:
            lines.append(f"- 最大回撤: {report.max_drawdown:.2%}")
        if report.volatility is not None:
            lines.append(f"- 年化波动率: {report.volatility:.2%}")
        lines.append(f"- 最大单基金占比: {report.max_single_weight:.1%} ({report.max_single_name})")
        lines.append(
            f"- 权益类: {report.equity_weight:.1%} | "
            f"债券类: {report.bond_weight:.1%} | QDII: {report.qdii_weight:.1%}"
        )

        if open_positions:
            lines.append("\n## 持仓明细")
            for p in open_positions:
                ret = (p.return_rate or 0) * 100
                lines.append(
                    f"- {p.fund_name}({p.fund_code}) {p.fund_type} | "
                    f"市值:{p.market_value:,.0f}({p.weight:.1%}) | "
                    f"收益:{ret:+.1f}% | 渠道:{p.channel or '未标注'}"
                )

        if report.flags:
            lines.append("\n## 系统风险提示")
            for f in report.flags:
                lines.append(f"- [{f.level}] {f.title}: {f.detail}")

        if advice:
            lines.append("\n## 系统结构建议")
            for a in advice:
                lines.append(f"- [{a.category}] {a.text}")

        # 大盘指数（可选，失败则跳过）
        market = _fetch_market_index()
        if market:
            lines.append(f"\n## 当前大盘指数\n{market}")

        return "\n".join(lines)
    except Exception as e:
        logger.exception("Failed to build portfolio context")
        return f"（持仓数据获取失败: {e}）"


def _fetch_market_index() -> str:
    """获取主要大盘指数数据（失败返回空字符串）。"""
    try:
        from datetime import datetime, timedelta

        import akshare as ak

        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
        results = []
        for symbol, name in [
            ("000001", "上证指数"),
            ("399001", "深证成指"),
            ("399006", "创业板指"),
        ]:
            try:
                df = ak.index_zh_a_hist(
                    symbol=symbol, period="daily",
                    start_date=start, end_date=end,
                )
                if df is not None and len(df) > 0:
                    last = df.iloc[-1]
                    close = float(last["收盘"])
                    change = float(last["涨跌幅"]) / 100
                    results.append(f"- {name}: {close:,.2f} ({change:+.2%})")
            except Exception:
                continue
        return "\n".join(results)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# 提供商识别 + web_search 工具构建
# ---------------------------------------------------------------------------
def detect_provider(base_url: str) -> str:
    """根据 base_url 识别提供商。"""
    url = base_url.lower()
    if "moonshot" in url or "kimi" in url:
        return "kimi"
    if "bigmodel" in url or "zhipu" in url or "glm" in url:
        return "zhipu"
    if "dashscope" in url or "aliyun" in url or "aliyuncs" in url or "maas" in url:
        return "qwen"
    if "deepseek" in url:
        return "deepseek"
    return "default"


def _build_tools(provider: str) -> tuple[list | None, dict[str, Any]]:
    """根据提供商构建 web_search 工具参数。

    返回 (tools, extra_params):
    - tools: 请求体中的 tools 字段，None 表示不启用
    - extra_params: 额外请求体参数
    """
    if provider == "kimi":
        return (
            [{"type": "builtin_function", "function": {"name": "$web_search"}}],
            {"thinking": {"type": "disabled"}},
        )
    if provider == "zhipu":
        return (
            [{"type": "web_search", "web_search": {"enable": True}}],
            {},
        )
    if provider == "qwen":
        return None, {
            "enable_search": True,
            "search_options": {"forced_search": True},
        }
    # deepseek / default / none: 不启用联网搜索
    return None, {}


def _build_system_prompt(context: str, has_search: bool = True) -> str:
    if has_search:
        core = """【核心要求】
1. 必须先搜索最新市场资讯，再结合用户持仓数据给出建议
2. 所有市场判断必须基于搜索到的真实资讯，不得凭空猜测
3. 引用资讯时请注明来源和日期
4. 建议要具体、可操作，但明确声明这不是交易指令
5. 如果搜索不到相关资讯，请如实告知，不要编造
6. 金额单位为人民币元"""
    else:
        core = """【核心要求】
1. 当前模型未启用联网搜索，请基于用户持仓数据和历史信息给出建议
2. 不得编造未经验证的市场数据或资讯
3. 如需最新市场行情，请提示用户自行查阅
4. 建议要具体、可操作，但明确声明这不是交易指令
5. 金额单位为人民币元"""

    return f"""你是 ZFundPilot 的 AI 投顾助手。你正在分析用户的基金持仓数据。

{core}

【交易记录录入能力】
你可以帮用户录入基金交易记录。当用户描述一笔交易（例如「我昨天在支付宝买了1000元005827」「上周卖出易方达蓝筹500份」），请提取信息并输出一个 ```json 代码块，格式如下：

```json
{{
  "tool": "add_transaction",
  "fund_code": "6位基金代码",
  "action": "buy|sell|dividend|reinvest",
  "date": "YYYY-MM-DD",
  "after_three": false,
  "amount": null,
  "shares": null,
  "nav": null,
  "fee": 0,
  "channel": "渠道",
  "note": ""
}}
```

字段规则：
- action 取值：buy(买入)、sell(卖出)、dividend(现金分红)、reinvest(红利再投资)
- buy：必填 amount（买入金额）；shares 可由 (amount-fee)/nav 自动算，留 null 即可
- sell：必填 shares（卖出份额）；amount 可由 shares*nav-fee 自动算，留 null 即可
- dividend：必填 amount（分红金额）；nav/fee/shares 不需要
- reinvest：必填 shares（红利份额）；fee 不需要
- after_three：布尔值。true 表示 15:00 后下单（按 T+1 次一交易日净值确认），false 或不确定时填 false（按当日净值确认）。用户提到「下午/晚上/收盘后」下单时设为 true
- 不确定的字段留 null，切勿编造数值
- channel 取值：支付宝、理财通、天天基金、基金公司直销、银行、券商、其它
- fund_code 必须是 6 位数字
- date 用户说「今天/昨天」时请推算实际日期；若不确定具体日期，留 null 让用户补填
- 输出 JSON 前，先用一句话简述你理解到的交易内容

除录入交易外，你仍然可以分析持仓、给出风险与调仓建议。但仅当用户明确表达要记录某笔交易时，才输出上述 JSON 块；前端会解析并让用户确认后才会真正写入。

以下是用户当前的持仓数据：

{context}"""


# ---------------------------------------------------------------------------
# 流式 SSE 解析辅助
# ---------------------------------------------------------------------------
def _merge_tool_calls(deltas: list) -> list[dict]:
    """合并流式 tool_call deltas 为完整的 tool_calls 列表。"""
    merged: dict[int, dict] = {}
    for delta_list in deltas:
        if not isinstance(delta_list, list):
            continue
        for tc in delta_list:
            idx = tc.get("index", 0)
            if idx not in merged:
                merged[idx] = {
                    "id": "",
                    "type": "function",
                    "function": {"name": "", "arguments": ""},
                }
            if "id" in tc:
                merged[idx]["id"] = tc["id"]
            if "type" in tc:
                merged[idx]["type"] = tc["type"]
            fn = tc.get("function", {})
            if "name" in fn:
                merged[idx]["function"]["name"] = fn["name"]
            if "arguments" in fn:
                merged[idx]["function"]["arguments"] += fn["arguments"]
    return [merged[i] for i in sorted(merged)]


# ---------------------------------------------------------------------------
# 核心：流式调用 LLM API
# ---------------------------------------------------------------------------
async def chat_stream(
    messages: list[dict],
    context: str,
) -> AsyncGenerator[str, None]:
    """流式调用 LLM API，自动处理 web_search 多轮 tool_calls。

    产出 SSE 格式的 JSON 字符串：
    - {"content": "文本片段"}  — 正常内容
    - {"status": "searching"} — 模型正在联网搜索
    - {"error": "错误信息"}    — 出错
    - {"done": true}          — 结束
    """
    if not config.AI_BASE_URL or not config.AI_API_KEY or not config.AI_MODEL:
        yield json.dumps({"error": "AI 模型未配置，请先到设置页面配置。"}, ensure_ascii=False)
        return

    provider = detect_provider(config.AI_BASE_URL) if config.AI_WEB_SEARCH else "none"
    tools, extra_params = _build_tools(provider)
    has_search = provider in ("kimi", "zhipu", "qwen")

    system_prompt = _build_system_prompt(context, has_search)
    full_messages = [{"role": "system", "content": system_prompt}] + messages

    url = f"{config.AI_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.AI_API_KEY}",
        "Content-Type": "application/json",
    }

    body: dict[str, Any] = {
        "model": config.AI_MODEL,
        "messages": full_messages,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if tools:
        body["tools"] = tools
    body.update(extra_params)

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            # 第一轮流式请求
            tool_calls_deltas: list = []
            has_tool_calls = False
            usage_acc = {"prompt": 0, "completion": 0, "total": 0}

            async with client.stream("POST", url, headers=headers, json=body) as resp:
                if resp.status_code != 200:
                    error_bytes = await resp.aread()
                    error_msg = error_bytes.decode("utf-8", errors="replace")[:500]
                    yield json.dumps(
                        {"error": f"API 返回 {resp.status_code}: {error_msg}"},
                        ensure_ascii=False,
                    )
                    return

                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)

                        # 捕获 token 用量（可能在单独的 chunk 中，此时 choices 为空数组）
                        if "usage" in chunk and chunk["usage"]:
                            u = chunk["usage"]
                            usage_acc["prompt"] += u.get("prompt_tokens", 0) or 0
                            usage_acc["completion"] += u.get("completion_tokens", 0) or 0
                            usage_acc["total"] += u.get("total_tokens", 0) or 0

                        choices = chunk.get("choices") or []
                        if not choices:
                            continue  # usage-only chunk 或心跳包

                        choice = choices[0]
                        delta = choice.get("delta", {})

                        # 直接流式输出内容
                        content = delta.get("content")
                        if content:
                            yield json.dumps({"content": content}, ensure_ascii=False)

                        # 收集 tool_calls（Kimi $web_search 多轮流）
                        if "tool_calls" in delta:
                            has_tool_calls = True
                            tool_calls_deltas.append(delta["tool_calls"])

                        if choice.get("finish_reason") == "tool_calls":
                            has_tool_calls = True
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

            # 如果返回了 tool_calls（Kimi 流程），处理多轮
            if has_tool_calls and tool_calls_deltas:
                yield json.dumps({"status": "searching"}, ensure_ascii=False)

                merged_tcs = _merge_tool_calls(tool_calls_deltas)

                # 构造 assistant 消息（含 tool_calls）
                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": merged_tcs,
                }

                # 构造 tool 结果消息（Kimi: 原样返回 arguments）
                tool_msgs = []
                for tc in merged_tcs:
                    tool_msgs.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "name": tc["function"]["name"],
                        "content": tc["function"]["arguments"],
                    })

                # 第二轮请求（带 tool 结果）
                body["messages"] = full_messages + [assistant_msg] + tool_msgs

                async with client.stream("POST", url, headers=headers, json=body) as resp2:
                    if resp2.status_code != 200:
                        error_bytes = await resp2.aread()
                        error_msg = error_bytes.decode("utf-8", errors="replace")[:500]
                        yield json.dumps(
                            {"error": f"API 返回 {resp2.status_code}: {error_msg}"},
                            ensure_ascii=False,
                        )
                        return

                    async for line in resp2.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)

                            # 捕获 token 用量（累加至第一轮结果上）
                            if "usage" in chunk and chunk["usage"]:
                                u = chunk["usage"]
                                usage_acc["prompt"] += u.get("prompt_tokens", 0) or 0
                                usage_acc["completion"] += u.get("completion_tokens", 0) or 0
                                usage_acc["total"] += u.get("total_tokens", 0) or 0

                            choices = chunk.get("choices") or []
                            if not choices:
                                continue

                            delta = choices[0].get("delta", {})
                            content = delta.get("content")
                            if content:
                                yield json.dumps({"content": content}, ensure_ascii=False)
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue

            # 有 token 用量 → 持久化 + 通知前端
            if usage_acc["total"] > 0:
                db.add_ai_usage(
                    config.AI_MODEL, usage_acc["prompt"],
                    usage_acc["completion"], usage_acc["total"],
                    len(messages),
                )
                yield json.dumps({"usage": usage_acc}, ensure_ascii=False)

            yield json.dumps({"done": True}, ensure_ascii=False)
    except httpx.ConnectError as e:
        yield json.dumps({"error": f"连接失败: {e}"}, ensure_ascii=False)
    except httpx.TimeoutException:
        yield json.dumps({"error": "请求超时（120s），请检查网络或重试"}, ensure_ascii=False)
    except Exception as e:
        logger.exception("LLM chat stream error")
        yield json.dumps({"error": f"内部错误: {e}"}, ensure_ascii=False)
