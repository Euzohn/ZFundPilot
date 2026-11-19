import { getCurrentLang } from "@/i18n/LanguageContext"
import type { NotificationSourceType } from "@/api/types"

type Bilingual = { zh: string; en: string }

function pick(b: Bilingual): string {
  return getCurrentLang() === "zh" ? b.zh : b.en
}

function pct(v: unknown): string {
  const n = Number(v)
  if (!isFinite(n)) return "—"
  return `${(n * 100).toFixed(1)}%`
}

function str(v: unknown): string {
  return v == null ? "" : String(v)
}

// ── 来源分组（图标名由组件映射 lucide）──
export const NOTIFICATION_SOURCES: Record<NotificationSourceType, Bilingual> = {
  dividend: { zh: "分红提醒", en: "Dividends" },
  tpsl: { zh: "止盈止损", en: "Take Profit / Stop Loss" },
  auto_invest: { zh: "定投计划", en: "Auto-Invest" },
  job: { zh: "后台任务", en: "Background Jobs" },
  nav_update: { zh: "净值更新", en: "NAV Update" },
  data_health: { zh: "数据健康", en: "Data Health" },
}

export function sourceLabel(source: string): string {
  const b = NOTIFICATION_SOURCES[source as NotificationSourceType]
  return b ? pick(b) : source
}

// ── 定投跳过原因（复用 auto_invest 稳定 skip_code）──
const SKIP_CODES: Record<string, Bilingual> = {
  suspended: { zh: "暂停申购", en: "subscription suspended" },
  limit_exceeded: { zh: "超出限购额度", en: "daily limit exceeded" },
  below_minimum: { zh: "低于申购起点", en: "below minimum purchase" },
}

const JOB_TYPES: Record<string, Bilingual> = {
  data_refresh: { zh: "数据刷新任务", en: "Data refresh job" },
  dca_backtest: { zh: "定投回测任务", en: "DCA backtest job" },
}

const ALERT_TYPES: Record<string, Bilingual> = {
  take_profit: { zh: "止盈", en: "Take profit" },
  stop_loss: { zh: "止损", en: "Stop loss" },
}

// ── 标题 code → 双语（params 插值；未知 code 降级显示 code 本身）──
type TitleFn = (p: Record<string, unknown>) => Bilingual

export const NOTIFICATION_TITLES: Record<string, TitleFn> = {
  dividend_detected: (p) => {
    const name = str(p.fund_name) || str(p.fund_code)
    const channel = str(p.channel)
    return {
      zh: `${name} 分红（除息日 ${str(p.ex_date)}${channel ? ` · ${channel}` : ""}）`,
      en: `${name} dividend (ex-date ${str(p.ex_date)}${channel ? ` · ${channel}` : ""})`,
    }
  },
  tp_sl_triggered: (p) => {
    const name = str(p.fund_name) || str(p.fund_code)
    const kind = ALERT_TYPES[str(p.alert_type)] ?? { zh: str(p.alert_type), en: str(p.alert_type) }
    return {
      zh: `${name} 触发${kind.zh}提醒（收益率 ${pct(p.triggered_return)}，阈值 ${pct(p.threshold)}）`,
      en: `${name} ${kind.en.toLowerCase()} alert (return ${pct(p.triggered_return)}, threshold ${pct(p.threshold)})`,
    }
  },
  auto_invest_skipped: (p) => {
    const name = str(p.fund_name) || str(p.fund_code)
    const skip = SKIP_CODES[str(p.skip_code)] ?? { zh: str(p.skip_code), en: str(p.skip_code) }
    return {
      zh: `定投跳过：${name}（${skip.zh}）`,
      en: `Auto-invest skipped: ${name} (${skip.en})`,
    }
  },
  auto_invest_error: (p) => {
    const name = str(p.fund_name) || str(p.fund_code)
    return {
      zh: `定投执行失败：${name}`,
      en: `Auto-invest failed: ${name}`,
    }
  },
  auto_invest_task_error: () => ({
    zh: "定投任务异常（本次未执行）",
    en: "Auto-invest task error (run aborted)",
  }),
  job_failed: (p) => {
    const job = JOB_TYPES[str(p.job_type)] ?? { zh: str(p.job_type), en: str(p.job_type) }
    return {
      zh: `${job.zh}失败`,
      en: `${job.en} failed`,
    }
  },
  job_interrupted: () => ({
    zh: "刷新任务中断（服务重启）",
    en: "Refresh job interrupted (service restart)",
  }),
  nav_update_failed: (p) => ({
    zh: `净值更新失败 ${str(p.count)} 只基金`,
    en: `NAV update failed for ${str(p.count)} fund(s)`,
  }),
  data_health_abnormal: (p) => {
    const parts: Bilingual[] = []
    const stale = Number(p.stale_nav_fund_count) || 0
    const missing = Number(p.missing_nav_fund_count) || 0
    const pending = Number(p.pending_t1_transaction_count) || 0
    if (stale > 0) parts.push({ zh: `${stale} 只净值过期`, en: `${stale} stale NAV` })
    if (missing > 0) parts.push({ zh: `${missing} 只缺净值`, en: `${missing} missing NAV` })
    if (pending > 0) parts.push({ zh: `${pending} 笔待确认`, en: `${pending} pending T+1` })
    const sep = getCurrentLang() === "zh" ? "、" : ", "
    return {
      zh: `数据健康异常：${parts.map((x) => x.zh).join(sep)}`,
      en: `Data health: ${parts.map((x) => x.en).join(sep)}`,
    }
  },
}

export function notificationTitle(code: string, params: Record<string, unknown>): string {
  const fn = NOTIFICATION_TITLES[code]
  if (!fn) return code
  return pick(fn(params || {}))
}

// ── 失效降级与跳转目标 ──
export const INVALID_SOURCE_LABEL: Bilingual = { zh: "已失效", en: "Expired" }

export function invalidSourceLabel(): string {
  return pick(INVALID_SOURCE_LABEL)
}

/** 通知来源页跳转目标（业务处理仍去原页面，通知中心只管「看过」）。 */
export function notificationTarget(n: { source_type: string }): string {
  switch (n.source_type) {
    case "dividend": return "/transactions"
    case "tpsl": return "/returns"
    case "auto_invest": return "/transactions?tab=auto-invest"
    case "job":
    case "nav_update": return "/nav"
    case "data_health": return "/overview"
    default: return "/overview"
  }
}