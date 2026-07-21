export const ACTION_LABELS: Record<string, string> = {
  buy: "买入",
  sell: "卖出",
  dividend: "分红",
  reinvest: "再投资",
}

export function actionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action
}
