import { getCurrentLang } from "@/i18n/LanguageContext"

// 中文区间标签（保留导出以兼容旧代码）
export const RANGE_LABELS: Record<string, string> = {
  "1m": "1月",
  "3m": "3月",
  "6m": "6月",
  "1y": "1年",
  "all": "全部",
  "hold": "持仓至今",
  "tx": "交易区间",
  "custom": "自定义",
}

// 英文区间标签
const RANGE_LABELS_EN: Record<string, string> = {
  "1m": "1M",
  "3m": "3M",
  "6m": "6M",
  "1y": "1Y",
  "all": "All",
  "hold": "Hold to date",
  "tx": "Tx range",
  "custom": "Custom",
}

// 中文周期标签（保留导出以兼容旧代码）
export const PERIOD_LABELS: Record<string, string> = {
  "1w": "近1周",
  "1m": "近1月",
  "3m": "近3月",
  "6m": "近6月",
  "1y": "近1年",
  "3y": "近3年",
  "ytd": "今年以来",
  "since": "成立以来",
}

// 英文周期标签
const PERIOD_LABELS_EN: Record<string, string> = {
  "1w": "1W",
  "1m": "1M",
  "3m": "3M",
  "6m": "6M",
  "1y": "1Y",
  "3y": "3Y",
  "ytd": "YTD",
  "since": "Since inception",
}

export const RANGE_DAYS: Record<string, number> = {
  "1m": 30,
  "3m": 90,
  "6m": 180,
  "1y": 365,
}

// 根据当前语言获取区间标签
export function getRangeLabel(range: string): string {
  const labels = getCurrentLang() === "zh" ? RANGE_LABELS : RANGE_LABELS_EN
  return labels[range] ?? range
}

// 根据当前语言获取周期标签
export function getPeriodLabel(period: string): string {
  const labels = getCurrentLang() === "zh" ? PERIOD_LABELS : PERIOD_LABELS_EN
  return labels[period] ?? period
}
