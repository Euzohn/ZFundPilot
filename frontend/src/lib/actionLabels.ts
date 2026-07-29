import { getCurrentLang } from "@/i18n/LanguageContext"

// 中文操作类型标签（保留导出以兼容旧代码）
export const ACTION_LABELS: Record<string, string> = {
  buy: "买入",
  sell: "卖出",
  dividend: "分红",
  reinvest: "再投资",
}

// 英文操作类型标签
const ACTION_LABELS_EN: Record<string, string> = {
  buy: "Buy",
  sell: "Sell",
  dividend: "Dividend",
  reinvest: "Reinvest",
}

export function actionLabel(action: string): string {
  const labels = getCurrentLang() === "zh" ? ACTION_LABELS : ACTION_LABELS_EN
  return labels[action] ?? action
}
