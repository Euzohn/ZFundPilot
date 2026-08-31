import { getCurrentLang } from "@/i18n/LanguageContext"

type Bilingual = { zh: string; en: string }

function pct(v: unknown): string {
  const n = Number(v) || 0
  return `${(n * 100).toFixed(1)}%`
}
function pct0(v: unknown): string {
  const n = Number(v) || 0
  return `${Math.round(n * 100)}%`
}

// ── Risk flags ──
export interface RiskFlagLabel {
  title: Bilingual
  detail: (p: Record<string, unknown>) => Bilingual
}

export const RISK_FLAGS: Record<string, RiskFlagLabel> = {
  single_fund_high: {
    title: { zh: "单基金集中度过高", en: "Single Fund Over-concentration" },
    detail: (p) => ({
      zh: `${p.name} 占比 ${pct(p.weight)}，超过 ${pct0(p.threshold)}，建议控制单一基金暴露。`,
      en: `${p.name} weight ${pct(p.weight)}, exceeds ${pct0(p.threshold)}. Consider reducing single fund exposure.`,
    }),
  },
  single_fund_warn: {
    title: { zh: "单基金集中度偏高", en: "Single Fund Concentration High" },
    detail: (p) => ({
      zh: `${p.name} 占比 ${pct(p.weight)}，超过 ${pct0(p.threshold)}。`,
      en: `${p.name} weight ${pct(p.weight)}, exceeds ${pct0(p.threshold)}.`,
    }),
  },
  equity_heavy: {
    title: { zh: "权益/成长风格偏重", en: "Equity / Growth Overweight" },
    detail: (p) => ({
      zh: `权益类资产占比 ${pct(p.weight)}，超过 ${pct0(p.threshold)}，组合波动可能较大。`,
      en: `Equity assets ${pct(p.weight)}, exceeds ${pct0(p.threshold)}. Portfolio volatility may be high.`,
    }),
  },
  bond_low: {
    title: { zh: "防守型资产偏低", en: "Defensive Assets Low" },
    detail: (p) => ({
      zh: `债券型占比仅 ${pct(p.weight)}，低于 ${pct0(p.threshold)}，组合缺乏缓冲。`,
      en: `Bond allocation only ${pct(p.weight)}, below ${pct0(p.threshold)}. Portfolio lacks buffer.`,
    }),
  },
  qdii_high: {
    title: { zh: "海外暴露较高", en: "Overseas Exposure High" },
    detail: (p) => ({
      zh: `QDII 占比 ${pct(p.weight)}，超过 ${pct0(p.threshold)}，注意汇率与海外市场波动。`,
      en: `QDII weight ${pct(p.weight)}, exceeds ${pct0(p.threshold)}. Mind FX and overseas market volatility.`,
    }),
  },
  drawdown_high: {
    title: { zh: "历史回撤较大", en: "Large Historical Drawdown" },
    detail: (p) => ({
      zh: `组合最大回撤 ${pct(p.value)}，低于 ${pct0(p.threshold)}，属高风险区间。`,
      en: `Max drawdown ${pct(p.value)}, below ${pct0(p.threshold)}. High risk zone.`,
    }),
  },
  volatility_high: {
    title: { zh: "波动率偏高", en: "High Volatility" },
    detail: (p) => ({
      zh: `组合年化波动率约 ${pct(p.value)}，超过 ${pct0(p.threshold)}。`,
      en: `Annualized volatility ~${pct(p.value)}, exceeds ${pct0(p.threshold)}.`,
    }),
  },
  no_risk: {
    title: { zh: "暂无明显风险提示", en: "No Significant Risk" },
    detail: () => ({
      zh: "当前组合各项风险指标处于设定阈值内。",
      en: "All risk indicators are within set thresholds.",
    }),
  },
}

export function translateRiskFlag(
  flag: { level: string; code: string; params: Record<string, unknown>; title: string; detail: string },
): { title: string; detail: string } {
  const label = RISK_FLAGS[flag.code]
  const lang = getCurrentLang()
  if (!label) return { title: flag.title, detail: flag.detail }
  const d = label.detail(flag.params || {})
  return { title: label.title[lang], detail: d[lang] }
}

// ── Rebalance advice ──
export interface AdviceLabel {
  category: Bilingual
  text: (p: Record<string, unknown>) => Bilingual
}

export const ADVICE: Record<string, AdviceLabel> = {
  no_holding: {
    category: { zh: "提示", en: "Info" },
    text: () => ({
      zh: "当前没有持仓数据，先添加基金后再查看结构建议。",
      en: "No holdings data. Add funds first to view structure advice.",
    }),
  },
  concentration_high: {
    category: { zh: "集中度", en: "Concentration" },
    text: (p) => ({
      zh: `单只基金「${p.name}」占比达 ${pct(p.weight)}，结构上高度依赖单一标的，可考虑将单一基金控制在 ${pct0(p.threshold)} 以内以分散风险。`,
      en: `Fund "${p.name}" weight ${pct(p.weight)}. Consider limiting single fund to ${pct0(p.threshold)} for diversification.`,
    }),
  },
  concentration_mid: {
    category: { zh: "集中度", en: "Concentration" },
    text: (p) => ({
      zh: `最大单基金「${p.name}」占比 ${pct(p.weight)}，集中度中等偏高，可适度均衡。`,
      en: `Largest fund "${p.name}" weight ${pct(p.weight)}. Consider moderate rebalancing.`,
    }),
  },
  equity_heavy: {
    category: { zh: "结构", en: "Structure" },
    text: (p) => ({
      zh: `权益类资产占比 ${pct(p.weight)}，组合偏成长/进攻；若希望降低波动，可提高债券等低波动资产比例。`,
      en: `Equity ${pct(p.weight)}, portfolio leans growth/offensive. Consider increasing bond allocation to reduce volatility.`,
    }),
  },
  bond_low: {
    category: { zh: "结构", en: "Structure" },
    text: (p) => ({
      zh: `债券型占比仅 ${pct(p.weight)}，防守型资产偏低，组合缺乏下行缓冲，可考虑提升至 ${pct0(p.threshold)} 以上。`,
      en: `Bond allocation only ${pct(p.weight)}. Consider raising to ${pct0(p.threshold)} for downside buffer.`,
    }),
  },
  qdii_high: {
    category: { zh: "风格", en: "Style" },
    text: (p) => ({
      zh: `QDII/海外资产占比 ${pct(p.weight)}，海外与汇率暴露较高，注意与 A 股资产的相关性及汇率波动。`,
      en: `QDII/overseas ${pct(p.weight)}. Mind correlation with A-shares and FX volatility.`,
    }),
  },
  sector_concentrated: {
    category: { zh: "板块", en: "Sector" },
    text: (p) => ({
      zh: `最大板块「${p.sector}」占比 ${pct(p.weight)}，板块集中度较高，单一主题回调时影响明显。`,
      en: `Top sector "${p.sector}" weight ${pct(p.weight)}. Sector concentration high, vulnerable to theme pullbacks.`,
    }),
  },
  tech_heavy: {
    category: { zh: "板块", en: "Sector" },
    text: (p) => ({
      zh: `科技/成长相关板块合计约 ${pct(p.weight)}，风格高度集中于科技成长，可考虑增加低相关性资产以平衡。`,
      en: `Tech/growth sectors total ~${pct(p.weight)}. Consider adding low-correlation assets for balance.`,
    }),
  },
  balanced: {
    category: { zh: "结构", en: "Structure" },
    text: () => ({
      zh: "当前组合结构相对均衡，暂无明显的结构性调整建议，可保持并持续跟踪。",
      en: "Portfolio structure is relatively balanced. No significant structural adjustments needed.",
    }),
  },
}

export function translateAdvice(
  advice: { code: string; params: Record<string, unknown>; category: string; text: string },
): { category: string; text: string } {
  const label = ADVICE[advice.code]
  const lang = getCurrentLang()
  if (!label) return { category: advice.category, text: advice.text }
  const t = label.text(advice.params || {})
  return { category: label.category[lang], text: t[lang] }
}

// ── Fee labels ──
export const FEE_LABELS: Record<string, Bilingual> = {
  fee_unknown: { zh: "费率未知", en: "Fee rate unknown" },
  purchase_rate: { zh: "申购费率", en: "Purchase fee rate" },
  purchase_fixed: { zh: "固定申购费", en: "Fixed purchase fee" },
  redemption_rate: { zh: "赎回费率", en: "Redemption fee rate" },
  pending_nav: { zh: "待确认净值后计算手续费", en: "Fee pending NAV confirmation" },
  no_buy_record: { zh: "无买入记录，无法计算持有期", en: "No buy records to calculate holding period" },
  amount_empty: { zh: "金额为空", en: "Amount is empty" },
  shares_empty: { zh: "份额为空", en: "Shares is empty" },
  date_empty: { zh: "日期为空", en: "Date is empty" },
  unsupported_action: { zh: "不支持的操作", en: "Unsupported action" },
}

export function translateFeeLabel(code: string, fallback: string): string {
  const lang = getCurrentLang()
  return FEE_LABELS[code]?.[lang] ?? fallback
}

// ── Estimate / Compare / Filter / FundMeta message codes ──
export const MESSAGE_CODES: Record<string, Bilingual> = {
  ok: { zh: "成功", en: "Success" },
  code_empty: { zh: "基金代码为空", en: "Fund code is empty" },
  not_found: { zh: "未找到", en: "Not found" },
  fetch_failed: { zh: "获取失败", en: "Fetch failed" },
  network_error: { zh: "网络请求失败", en: "Network request failed" },
  meta_failed: { zh: "获取基本信息失败", en: "Failed to get fund info" },
  meta_error: { zh: "获取基本信息异常", en: "Fund info error" },
  codes_empty: { zh: "基金代码列表为空", en: "Fund code list is empty" },
  too_many: { zh: "一次最多对比 20 只基金", en: "Maximum 20 funds per comparison" },
  all_failed: { zh: "所有基金获取失败", en: "All fund fetches failed" },
  exception: { zh: "处理异常", en: "Processing error" },
  fetch_error: { zh: "净值获取失败", en: "NAV fetch error" },
  universe_failed: { zh: "基金池加载失败，请稍后重试", en: "Fund universe load failed, please retry" },
}

export function translateMessage(code: string, fallback: string): string {
  const lang = getCurrentLang()
  return MESSAGE_CODES[code]?.[lang] ?? fallback
}
