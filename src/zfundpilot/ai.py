"""AI 投顾模块 — 持仓上下文构建 + 提供商识别 + LLM 流式调用（含联网搜索）。

支持 OpenAI 兼容 API，根据 base_url 自动识别提供商（智谱/Kimi/通义千问），
并启用对应格式的联网搜索（web_search）。
"""

from __future__ import annotations

import base64
import json
import logging
import re
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
                avg_nav = f"{p.avg_cost_nav:.4f}" if p.avg_cost_nav else "—"
                latest_nav = f"{p.latest_nav:.4f}" if p.latest_nav else "—"
                lines.append(
                    f"- {p.fund_name}({p.fund_code}) {p.fund_type} | "
                    f"份额:{p.held_shares:,.2f} | "
                    f"成本:{p.total_cost:,.0f} | "
                    f"市值:{p.market_value:,.0f}({p.weight:.1%}) | "
                    f"收益:{ret:+.1f}% | "
                    f"均价:{avg_nav} | "
                    f"最新净值:{latest_nav} | "
                    f"渠道:{p.channel or '未标注'}"
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
    if provider == "deepseek":
        return (
            [{"type": "web_search"}],
            {},
        )
    # default / none: 不启用联网搜索
    return None, {}


def _build_system_prompt(context: str, has_search: bool = True) -> str:
    custom = config.AI_CUSTOM_PROMPT.strip()
    custom_block = f"【用户自定义指令】\n{custom}\n\n" if custom else ""

    search_rules = (
        "- 优先搜索最新市场资讯，结合持仓数据给出建议\n"
        "- 引用资讯请注明来源和日期\n"
        "- 搜索不到时如实告知，不编造"
    ) if has_search else (
        "- 基于持仓数据和历史信息分析\n"
        "- 不编造未经验证的市场数据\n"
        "- 如需最新行情，提示用户自行查阅"
    )

    return f"""{custom_block}你是 ZFundPilot AI 投顾助手，专注于中国公募基金投资分析。

【角色定位】
- 擅长：持仓分析、风险评估、资产配置建议、定投策略
- 不做：个股推荐、短线交易信号、涨跌预测
- 格式：Markdown（表格/分点/加粗），回答简洁专业
- 语言：跟随用户提问语言
- 金额单位为人民币元

【联网搜索】
{search_rules}

【分析框架】
分析持仓时从以下维度展开：
1. 资产配置：权益类/债券类/QDII 比例是否均衡
2. 集中度：单基金占比（>20% 需关注）
3. 风险收益：最大回撤、波动率、收益率
4. 渠道分布：是否过度依赖单一渠道
5. 结构优化：参考系统已生成的风险提示和建议

【持仓数据字段说明】
- 份额：当前持有份额（卖出/清仓时直接引用此值填入 shares）
- 成本：当前持仓成本（已扣卖出结转）
- 市值：按最新净值计算的当前市值
- 均价：持仓平均成本净值
- 最新净值：最近一期的单位净值
- 收益：浮动收益率

【风险声明】
所有分析仅供参考，不构成投资建议或交易指令。投资有风险，决策需谨慎。

【交易记录录入】
当用户描述一笔交易（如「昨天在支付宝买了1000元005827」「清仓易方达蓝筹」），提取信息并输出 ```json 代码块：

```json
{{
  "tool": "add_transaction",
  "fund_code": "6位代码",
  "action": "buy|sell|dividend|reinvest",
  "date": "YYYY-MM-DD",
  "after_three": false,
  "amount": null,
  "shares": null,
  "nav": null,
  "fee": 0,
  "channel": "",
  "note": ""
}}
```

字段规则：
- action：buy(买入)、sell(卖出)、dividend(现金分红)、reinvest(红利再投资)
- buy：必填 amount（买入金额）
- sell：必填 shares（卖出份额）；用户说「清仓/全部卖出」时，shares 直接用持仓明细中的「份额」值
- dividend：必填 amount（分红金额）；nav/fee/shares 不需要
- reinvest：必填 shares（红利份额）；fee 不需要
- after_three：15:00 后下单设 true（T+1 次日净值确认）
- channel：支付宝/理财通/天天基金/银行/券商/其它
- fund_code 必须是 6 位数字
- date：用户说「今天/昨天」时推算实际日期；不确定时留 null 让用户补填
- 不确定的字段留 null，切勿编造
- 输出 JSON 前先用一句话简述理解到的交易内容
- 仅当用户明确表达要记录交易时才输出 JSON 块

以下是用户当前的持仓数据：

{context}"""


def build_system_prompt(include_context: bool = True) -> str:
    """构建当前配置下的系统提示（含持仓快照 + 搜索能力判断）。供 API 端点调用。"""
    context = build_portfolio_context() if include_context else ""
    provider = detect_provider(config.AI_BASE_URL) if config.AI_WEB_SEARCH else "none"
    has_search = provider in ("kimi", "zhipu", "qwen", "deepseek")
    return _build_system_prompt(context, has_search)


def test_connection() -> dict:
    """测试当前 AI 配置是否可用（发最小非流式请求）。"""
    if not config.AI_BASE_URL or not config.AI_API_KEY or not config.AI_MODEL:
        return {"ok": False, "error": "配置不完整（Base URL / API Key / Model）"}
    try:
        url = f"{config.AI_BASE_URL.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {config.AI_API_KEY}",
            "Content-Type": "application/json",
        }
        body = {
            "model": config.AI_MODEL,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
            "stream": False,
        }
        resp = httpx.post(url, headers=headers, json=body, timeout=15)
        if resp.status_code == 200:
            provider = detect_provider(config.AI_BASE_URL)
            has_search = config.AI_WEB_SEARCH and provider in ("kimi", "zhipu", "qwen", "deepseek")
            return {"ok": True, "provider": provider, "model": config.AI_MODEL, "has_search": has_search}
        logger.error("AI 测试连接返回 %s: %s", resp.status_code, resp.text[:300])
        return {"ok": False, "error": f"API 返回 {resp.status_code}"}
    except httpx.ConnectError:
        logger.exception("AI 测试连接失败（网络错误）")
        return {"ok": False, "error": "连接失败，请检查 Base URL 或网络"}
    except httpx.TimeoutException:
        return {"ok": False, "error": "请求超时（15s）"}
    except Exception:
        logger.exception("AI 测试连接异常")
        return {"ok": False, "error": "连接失败，请稍后再试"}


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
    has_search = provider in ("kimi", "zhipu", "qwen", "deepseek")

    # 若前端已携带 system 消息（新对话首条已取过），直接用；否则构建并前置（向后兼容）
    has_system = any(m.get("role") == "system" for m in messages)
    if has_system:
        full_messages = messages
    else:
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


# ---------------------------------------------------------------------------
# 视觉模型 — 截图解析（交易流水 / 持仓对账）
# ---------------------------------------------------------------------------
# 1x1 红点 PNG，用于测试视觉模型是否支持图片输入
_TEST_PNG_B64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="


def _build_screenshot_prompt(mode: str, channel_hint: str = "") -> str:
    """根据模式构建视觉解析提示词。布局无关，适用于支付宝/理财通/天天基金/银行 app 截图。"""
    if mode == "holdings":
        return """你是基金持仓截图解析助手。从用户上传的截图中提取当前持仓信息。

提取字段，输出 JSON 数组，每元素：
- fund_name: 基金名称（必填，从截图中识别）
- fund_code: 6 位代码（截图可见则填，否则填 null，切勿编造）
- shares: 持有份额（数字，不确定填 null）
- market_value: 当前市值（数字，不确定填 null）

规则：
- fund_code 不确定时填 null，切勿编造
- 不确定的数值填 null，切勿编造
- 只输出 JSON 数组，不要输出任何其他文字
- 截图中有几只基金就输出几个元素"""

    # transactions 模式
    channel_line = f"\n- 渠道：可参考「{channel_hint}」，但从截图 UI 识别到的渠道优先" if channel_hint else "\n- 渠道：从截图 UI 识别（支付宝/理财通/天天基金/银行/券商/其它），识别不到留空串"
    return f"""你是基金交易截图解析助手。从用户上传的截图中提取交易记录。

提取字段，输出 JSON 数组，每元素：
- fund_name: 基金名称（必填，从截图中识别）
- fund_code: 6 位代码（截图可见则填，否则填 null，切勿编造）
- action: 交易类型，buy(买入)、sell(卖出)、dividend(现金分红)、reinvest(红利再投资)
- date: YYYY-MM-DD 格式日期（不确定填 null）
- amount: 金额（数字，不确定填 null）
- shares: 份额（数字，不确定填 null）
- nav: 单位净值（数字，不确定填 null）
- fee: 手续费（数字，不确定填 null，无则填 0）
- channel: 渠道（支付宝/理财通/天天基金/银行/券商/其它）
- is_t1: 截图显示「待确认」「T+1」「15:00 后下单」时为 true，否则 false

规则：
- 单笔确认页或多行流水列表都输出 JSON 数组
- 买入待确认：amount 已知、shares 填 null、is_t1 为 true
- fund_code 不确定时填 null，切勿编造
- 不确定的数值填 null，切勿编造
- 只输出 JSON 数组，不要输出任何其他文字
{channel_line}"""


def _extract_json_list(content: str) -> list | None:
    """从模型返回内容中提取 JSON 数组。容错：```json 块 / 裸 JSON / 前后多余文字。"""
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
    if m:
        try:
            parsed = json.loads(m.group(1).strip())
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
    try:
        parsed = json.loads(content.strip())
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass
    start = content.find("[")
    end = content.rfind("]")
    if start != -1 and end > start:
        try:
            parsed = json.loads(content[start : end + 1])
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
    return None


def _resolve_codes(items: list[dict]) -> list[dict]:
    """对每条记录用 fund universe 解析名称→代码，填充 code_status + candidates。

    - 模型给了 code → 校验是否在 universe，不存在则丢弃走名称匹配（防编造）
    - 仅有 name → resolve_fund_code 精确/多候选/无匹配
    """
    from . import fund_filter

    for item in items:
        name = str(item.get("fund_name", "") or "")
        code = item.get("fund_code")
        if code:
            code = str(code).strip()
            if code and fund_filter.verify_fund_code(code):
                item["fund_code"] = code
                item["code_status"] = "exact"
                item["candidates"] = []
                continue
            # code 不在 universe，丢弃走名称匹配
            item["fund_code"] = None
        result = fund_filter.resolve_fund_code(name)
        item["fund_code"] = result["code"]
        item["code_status"] = result["status"]
        item["candidates"] = result["candidates"]
    return items


def parse_screenshot(image_bytes: bytes, mode: str, channel_hint: str = "") -> dict:
    """调用视觉模型解析截图，返回结构化数据。

    mode: "transactions"（交易流水）| "holdings"（持仓对账）
    返回 {"ok": bool, "items": [...], "error": str}。
    每条 item 的 fund_code 已通过 resolve_fund_code 后处理填充/标记。
    不写库，交前端预览编辑后批量保存。
    """
    if not config.AI_VISION_BASE_URL or not config.AI_VISION_API_KEY or not config.AI_VISION_MODEL:
        return {"ok": False, "items": [], "error": "视觉模型未配置，请先到设置页面配置。"}

    prompt = _build_screenshot_prompt(mode, channel_hint)
    data_url = "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("ascii")

    url = f"{config.AI_VISION_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.AI_VISION_API_KEY}",
        "Content-Type": "application/json",
    }
    body: dict[str, Any] = {
        "model": config.AI_VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
        "stream": False,
    }

    try:
        resp = httpx.post(url, headers=headers, json=body, timeout=60)
        if resp.status_code != 200:
            return {"ok": False, "items": [], "error": f"API 返回 {resp.status_code}: {resp.text[:200]}"}
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            return {"ok": False, "items": [], "error": "模型未返回内容"}
        content = choices[0].get("message", {}).get("content", "")
        items = _extract_json_list(content)
        if items is None:
            return {"ok": False, "items": [], "error": "模型返回内容无法解析为 JSON"}
        items = _resolve_codes(items)
        return {"ok": True, "items": items, "error": ""}
    except httpx.ConnectError:
        logger.exception("parse_screenshot 连接失败")
        return {"ok": False, "items": [], "error": "连接失败，请检查网络或 Base URL"}
    except httpx.TimeoutException:
        return {"ok": False, "items": [], "error": "请求超时（60s），请稍后重试"}
    except Exception as e:
        logger.exception("parse_screenshot 异常")
        return {"ok": False, "items": [], "error": f"内部错误: {e}"}


def test_vision_connection() -> dict:
    """测试视觉模型是否可用（发 1×1 测试图，验证模型支持图片输入）。"""
    if not config.AI_VISION_BASE_URL or not config.AI_VISION_API_KEY or not config.AI_VISION_MODEL:
        return {"ok": False, "error": "配置不完整（Base URL / API Key / Model）"}
    try:
        data_url = f"data:image/png;base64,{_TEST_PNG_B64}"
        url = f"{config.AI_VISION_BASE_URL.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {config.AI_VISION_API_KEY}",
            "Content-Type": "application/json",
        }
        body = {
            "model": config.AI_VISION_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "回复 ok"},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            "max_tokens": 10,
            "stream": False,
        }
        resp = httpx.post(url, headers=headers, json=body, timeout=30)
        if resp.status_code == 200:
            return {"ok": True, "model": config.AI_VISION_MODEL}
        logger.error("视觉模型测试返回 %s: %s", resp.status_code, resp.text[:300])
        return {"ok": False, "error": f"API 返回 {resp.status_code}（模型可能不支持图片输入）"}
    except httpx.ConnectError:
        return {"ok": False, "error": "连接失败，请检查 Base URL 或网络"}
    except httpx.TimeoutException:
        return {"ok": False, "error": "请求超时（30s）"}
    except Exception:
        logger.exception("视觉模型测试连接异常")
        return {"ok": False, "error": "连接失败，请稍后再试"}
