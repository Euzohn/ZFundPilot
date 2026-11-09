import { getCurrentLang } from "@/i18n/LanguageContext"
import type { ProposalSummary } from "@/api/types"

// 账本操作类型（operation_type）标签，双语；与后端 OPERATION_LABELS code 对应。
const OPERATION_LABELS: Record<string, string> = {
  add_transaction: "新增交易",
  update_transaction: "修改交易",
  delete_transaction: "删除交易",
  add_conversion: "基金转换",
  delete_conversion: "删除转换",
  batch_import: "批量导入",
  create_plan: "创建定投",
  update_plan: "修改定投",
  toggle_plan: "启停定投",
  delete_plan: "删除定投",
  resolve_alert: "处理提醒",
  backfill_transaction_navs: "回填净值",
  execute_plan: "手动执行定投",
}

const OPERATION_LABELS_EN: Record<string, string> = {
  add_transaction: "Add transaction",
  update_transaction: "Update transaction",
  delete_transaction: "Delete transaction",
  add_conversion: "Fund conversion",
  delete_conversion: "Delete conversion",
  batch_import: "Batch import",
  create_plan: "Create auto-invest",
  update_plan: "Update auto-invest",
  toggle_plan: "Toggle auto-invest",
  delete_plan: "Delete auto-invest",
  resolve_alert: "Resolve alert",
  backfill_transaction_navs: "Backfill NAV",
  execute_plan: "Run auto-invest",
}

export function operationLabel(operationType: string): string {
  const labels =
    getCurrentLang() === "zh" ? OPERATION_LABELS : OPERATION_LABELS_EN
  return labels[operationType] ?? operationType
}

// 回填手续费来源（fee_source）标签。
const FEE_SOURCE_LABELS: Record<string, string> = {
  existing: "沿用原手续费",
  fetched: "抓取费率",
  explicit: "显式提供",
  needs_fee: "需提供手续费",
}

const FEE_SOURCE_LABELS_EN: Record<string, string> = {
  existing: "Existing fee",
  fetched: "Fetched rate",
  explicit: "Explicit fee",
  needs_fee: "Fee required",
}

export function feeSourceLabel(source: string | null | undefined): string {
  if (!source) return ""
  const labels =
    getCurrentLang() === "zh" ? FEE_SOURCE_LABELS : FEE_SOURCE_LABELS_EN
  return labels[source] ?? source
}

// 提醒类型（alert_type）标签。
const ALERT_TYPE_LABELS: Record<string, string> = {
  dividend: "分红提醒",
  take_profit: "止盈提醒",
  stop_loss: "止损提醒",
}

const ALERT_TYPE_LABELS_EN: Record<string, string> = {
  dividend: "Dividend alert",
  take_profit: "Take-profit alert",
  stop_loss: "Stop-loss alert",
}

export function alertTypeLabel(alertType: string | null | undefined): string {
  if (!alertType) return "—"
  const labels =
    getCurrentLang() === "zh" ? ALERT_TYPE_LABELS : ALERT_TYPE_LABELS_EN
  return labels[alertType] ?? alertType
}

// 定投频率（cadence）+ 排期（schedule）标签：基于稳定 code 重拼，不依赖后端中文。
const CADENCE_LABELS: Record<string, string> = {
  daily: "每日",
  week: "每周",
  biweek: "每两周",
  month: "每月",
}

const CADENCE_LABELS_EN: Record<string, string> = {
  daily: "Daily",
  week: "Weekly",
  biweek: "Bi-weekly",
  month: "Monthly",
}

const WEEKDAY_CHARS = "一二三四五六日" // day_of_week 0=周一，与后端一致
const WEEKDAYS_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

export function cadenceLabel(cadence: string | null | undefined): string {
  if (!cadence) return "—"
  const labels = getCurrentLang() === "zh" ? CADENCE_LABELS : CADENCE_LABELS_EN
  return labels[cadence] ?? cadence
}

export function planScheduleLabel(summary: ProposalSummary): string {
  const { cadence, day_of_week, day_of_month } = summary
  const zh = getCurrentLang() === "zh"
  if (cadence === "week" && day_of_week !== null && day_of_week !== undefined) {
    return zh
      ? `每周${WEEKDAY_CHARS[day_of_week]}`
      : `Weekly on ${WEEKDAYS_EN[day_of_week]}`
  }
  if (cadence === "biweek" && day_of_week !== null && day_of_week !== undefined) {
    return zh
      ? `每两周的周${WEEKDAY_CHARS[day_of_week]}`
      : `Bi-weekly on ${WEEKDAYS_EN[day_of_week]}`
  }
  if (cadence === "month" && day_of_month !== null && day_of_month !== undefined) {
    return zh ? `每月${day_of_month}日` : `Monthly on day ${day_of_month}`
  }
  return cadenceLabel(cadence)
}

// 提案标题（title）：后端 title 是拼接好的中文，这里基于稳定 code 重拼，双语。
export function proposalTitle(summary: ProposalSummary): string {
  const zh = getCurrentLang() === "zh"
  const op = summary.operation_type
  switch (op) {
    case "add_transaction":
    case "update_transaction":
    case "delete_transaction": {
      const verb = actionVerb(op, summary.action, zh)
      return `${verb} ${summary.fund_code}`.trim()
    }
    case "add_conversion":
    case "delete_conversion": {
      const from = summary.conversion?.from.fund_code || summary.fund_code
      const to = summary.conversion?.to.fund_code
      const prefix =
        op === "add_conversion"
          ? zh ? "转换" : "Convert"
          : zh ? "删除转换" : "Delete conversion"
      return to ? `${prefix} ${from} → ${to}` : `${prefix} ${from}`
    }
    case "batch_import": {
      const n = summary.count ?? 0
      return zh ? `批量导入 ${n} 条交易` : `Batch import ${n} transactions`
    }
    case "resolve_alert": {
      const label = alertTypeLabel(summary.alert_type)
      return zh
        ? `处理${label} #${summary.alert_id ?? ""}`
        : `Resolve ${label.replace(" alert", "")} alert #${summary.alert_id ?? ""}`
    }
    case "backfill_transaction_navs": {
      const n = summary.count ?? 0
      return zh ? `回填净值 ${n} 条` : `Backfill NAV for ${n} transactions`
    }
    case "create_plan":
      return zh
        ? `创建定投计划 ${summary.fund_code}`
        : `Create auto-invest plan ${summary.fund_code}`
    case "update_plan":
      return zh
        ? `修改定投计划 #${summary.plan_id ?? ""}`
        : `Update auto-invest plan #${summary.plan_id ?? ""}`
    case "toggle_plan": {
      const enabling = summary.enabled_after !== false
      return zh
        ? `${enabling ? "启用" : "停用"}定投计划 #${summary.plan_id ?? ""}`
        : `${enabling ? "Enable" : "Disable"} auto-invest plan #${summary.plan_id ?? ""}`
    }
    case "delete_plan":
      return zh
        ? `删除定投计划 #${summary.plan_id ?? ""}`
        : `Delete auto-invest plan #${summary.plan_id ?? ""}`
    case "execute_plan":
      return zh
        ? `手动执行定投计划 #${summary.plan_id ?? ""}`
        : `Run auto-invest plan #${summary.plan_id ?? ""}`
    default:
      return summary.title || operationLabel(op)
  }
}

// 新增/修改/删除交易标题里的动词（含方向）。
function actionVerb(
  op: string,
  action: string | undefined,
  zh: boolean,
): string {
  const side = action === "sell" ? (zh ? "卖出" : "Sell") : zh ? "买入" : "Buy"
  if (op === "update_transaction") return `${zh ? "修改" : "Update"} ${side}`
  if (op === "delete_transaction") return `${zh ? "删除" : "Delete"} ${side}`
  return side
}
