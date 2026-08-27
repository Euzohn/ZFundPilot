export interface Fund {
  fund_code: string
  fund_name: string
  fund_type: string
  sector: string
  tracking_index: string
  dividend_method?: string
}

export interface DividendEvent {
  fund_code: string
  fund_name: string
  record_date: string
  ex_date: string
  per_share: number
  pay_date: string
  held_shares: number
  estimated_amount: number
  dividend_method: string
}

export interface DividendAlert {
  id: number
  fund_code: string
  fund_name: string
  record_date?: string
  ex_date?: string
  per_share?: number
  pay_date?: string
  held_shares?: number
  estimated_amount?: number
  dividend_method?: string
  alert_type?: string
  triggered_return?: number
  threshold?: number
  status: "pending" | "confirmed" | "ignored"
  created_at: string
  resolved_at?: string
  tx_id?: number
}

export interface TpSlConfig {
  enabled: string
  take_profit_enabled: string
  stop_loss_enabled: string
  take_profit: string
  stop_loss: string
  reset_ratio: string
}

export interface Transaction {
  id?: number
  fund_code: string
  action: string
  date: string
  amount: number | null
  shares: number | null
  nav: number | null
  fee: number
  channel: string
  note: string
  is_t1?: boolean
}

export interface Position {
  fund_code: string
  fund_name: string
  fund_type: string
  sector: string
  channel: string
  tracking_index: string
  held_shares: number
  total_cost: number
  avg_cost_nav: number | null
  latest_nav: number | null
  latest_date: string | null
  market_value: number
  unrealized_pnl: number
  realized_pnl: number
  return_rate: number | null
  weight: number
  buy_count: number
  sell_count: number
  dividend_count: number
  dividend_total: number
  total_pnl: number
  is_open: boolean
}

export interface PortfolioSummary {
  total_cost: number
  total_value: number
  unrealized_pnl: number
  realized_pnl: number
  total_pnl: number
  total_return: number
  total_buy: number
  total_sell: number
  total_dividend: number
  holding_count: number
  max_single_weight: number
  max_single_name: string
  as_of_date: string | null
  daily_pnl: number
  daily_return: number
  week_pnl: number
  week_return: number
  month_pnl: number
  month_return: number
  year_pnl: number
  year_return: number
}

export interface CurvePoint {
  date: string
  total_value: number
  invested_cost: number
  total_return: number
  [key: string]: string | number
}

export interface BenchmarkPoint {
  date: string
  [code: string]: string | number
}

export interface ChannelPnLPoint {
  date: string
  [channel: string]: string | number
}

export interface DistributionItem {
  [key: string]: string | number
  market_value: number
  weight: number
}

export interface RiskReport {
  max_drawdown: number | null
  volatility: number | null
  max_single_weight: number
  max_single_name: string
  hhi: number
  equity_weight: number
  bond_weight: number
  qdii_weight: number
  flags: RiskFlag[]
}

export interface RiskFlag {
  level: string
  code: string
  params: Record<string, unknown>
  title: string
  detail: string
}

export interface Advice {
  code: string
  params: Record<string, unknown>
  category: string
  text: string
}

export interface FetchResult {
  fund_code: string
  ok: boolean
  written: number
  message: string
  code: string
  latest_date: string | null
  latest_nav: number | null
}

export interface NavUpdateStatus {
  running: boolean
  total: number
  done: number
  current: string
  results: FetchResult[]
  error: string
}

export interface FundMeta {
  fund_code: string
  fund_name: string
  fund_type: string
  sector: string
  tracking_index: string
  dividend_method?: string
  ok: boolean
  message: string
}

export interface LatestNav {
  fund_code: string
  fund_name: string
  fund_type: string
  sector: string
  date: string | null
  nav: number | null
}

export interface CSVParseResult {
  transactions: Transaction[]
  errors: string[]
}

export interface AIUsageRow {
  id: number
  created_at: string
  model: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  turns: number
}

export interface AIUsageStats {
  today: number
  total: number
  recent: AIUsageRow[]
}

export interface AIUsageDaily {
  date: string
  tokens: number
}

// ── 费率 ──
export interface PurchaseTier {
  min_amount: number
  max_amount: number | null
  rate: number
  is_fixed: boolean
  fixed_fee: number
  label: string
}

export interface RedemptionTier {
  min_days: number
  max_days: number | null
  rate: number
}

export interface FeeRatesResponse {
  ok: boolean
  fund_code: string
  message: string
  purchase: PurchaseTier[]
  redemption: RedemptionTier[]
  management_fee: number | null
  custodian_fee: number | null
  sales_fee: number | null
}

export interface CalcFeeResponse {
  fee: number
  rate: number
  label: string
  code: string
  amount: number
  nav: number | null
  lots: FeeLot[] | null
}

export interface FeeLot {
  buy_date: string
  buy_shares: number
  used_shares: number
  days_held: number
  rate: number
  fee: number
}

// ── 基金持仓 ──
export interface Holding {
  stock_code: string
  stock_name: string
  weight: number           // 占净值比例（小数，0.05 = 5%）
  shares: number           // 持股数（万股）
  market_value: number     // 持仓市值（万元）
  quarter: string          // 报告期
}

export interface FundHoldings {
  ok: boolean
  fund_code: string
  message: string
  code: string
  holdings: Holding[]
  stock_ratio: number
  bond_ratio: number
  cash_ratio: number
  other_ratio: number
  quarter: string
}

// ── 同类排名走势 ──
export interface RankingPoint {
  date: string
  percentile: number          // 排名百分位（0-100，越低越好）
}

export interface FundRanking {
  ok: boolean
  fund_code: string
  message: string
  code: string
  points: RankingPoint[]
}

// ── 基金档案 ──
export interface FundProfile {
  ok: boolean
  fund_code: string
  message: string
  code: string
  manager: string
  manager_career_days: number | null   // 累计从业天数
  scale: number | null                 // 现任基金资产总规模（亿元）
  tenure_return: number | null         // 基金经理任期收益（%）
  management_fee: number | null
  custodian_fee: number | null
  sales_fee: number | null
  risk_level: string                  // 风险等级
}

// ── 关键词映射 ──
export interface KeywordEntry {
  keyword: string
  mapped: string
}

export interface KeywordMaps {
  type_defaults: KeywordEntry[]
  sector_defaults: KeywordEntry[]
  type_custom: KeywordEntry[]
  sector_custom: KeywordEntry[]
  available_types: string[]
  available_sectors: string[]
}

// ── 定时任务 ──
export interface SchedulerStatus {
  enabled: boolean
  cron: string
  next_run: string | null
  last_run: string | null
  last_results: { fund_code: string; ok: boolean; written: number; latest_date: string | null; latest_nav: number | null }[] | null
  dividend_enabled: boolean
  dividend_last_run: string | null
  tp_sl_enabled: boolean
  tp_sl_last_run: string | null
}

// ── 实时估值 ──
export interface FundEstimateItem {
  fund_code: string
  fund_name: string
  held_shares: number
  dwjz: number
  gsz: number
  gszzl: number
  gztime: string
  estimated_pnl: number
  prev_value: number
  ok: boolean
  message: string
  code: string
}

export interface EstimateSummary {
  funds: FundEstimateItem[]
  total_estimated_pnl: number
  estimated_return: number
  gztime: string
}

export interface FundEstimate {
  fund_code: string
  fund_name: string
  jzrq: string
  dwjz: number
  gsz: number
  gszzl: number
  gztime: string
  ok: boolean
  message: string
  code: string
}

// ── 审计日志 ──
export interface AuditLog {
  id: number
  ts: string
  ip: string | null
  username: string | null
  action: string
  detail: string | null
}

// ── 基金对比 ──
export interface FundCompareItem {
  code: string
  name: string
  type: string
  sector: string
  inception_date: string
  scale: number | null
  manager: string
  management_fee: number | null
  custodian_fee: number | null
  sales_fee: number | null
  returns: Record<string, number | null>
  risk: Record<string, number | null>
  latest_nav: number | null
  latest_date: string | null
  ok: boolean
  message: string
  msg_code: string
}

export interface CompareResponse {
  funds: FundCompareItem[]
  correlations: (number | null)[][] | null
  nav_series: Record<string, { date: string; value: number }[]> | null
  ok: boolean
  message: string
  msg_code: string
}

// ── 基金筛选 ──
export interface FundFilterItem {
  code: string
  name: string
  type: string
  sector: string
  scale: number | null
  manager: string
  inception_date: string
  returns: Record<string, number | null> | null
  risk: Record<string, number | null> | null
}

export interface FilterResponse {
  funds: FundFilterItem[]
  total: number
  ok: boolean
  message: string
  code: string
}

// ── 自选关注列表 ──
export interface WatchlistItem {
  fund_code: string
  note: string
  group_name: string
  added_at: string
  fund_name: string
  fund_type: string
  sector: string
  tracking_index: string
}

// ── 定投回测 ──
export interface BacktestResult {
  fund_code: string
  fund_name: string
  strategy: string         // "dca" / "lumpsum"
  period_start: string
  period_end: string
  cadence: string          // "month" / "biweek" / "week"
  amount_per_period: number
  total_periods: number
  invested_capital: number
  total_fees: number
  final_value: number
  redemption_fee: number
  net_final_value: number
  total_return: number
  annualized_return: number | null
  max_drawdown: number | null
  sharpe_ratio: number | null
  curve: BacktestCurvePoint[]
  periods_detail: BacktestPeriodDetail[]
}

export interface BacktestCurvePoint {
  date: string
  invested: number
  value: number
  return: number
}

export interface BacktestPeriodDetail {
  planned_date: string
  actual_date: string
  nav: number
  amount: number
  fee: number
  invested: number
  shares: number
  cumulative_shares: number
  cumulative_invested: number
}

export interface DcaBacktestResponse {
  results: BacktestResult[]
  ok: boolean
  message: string
}

// ── 定投计划 ──
export interface AutoInvestPlan {
  id: number
  fund_code: string
  fund_name?: string
  amount: number
  cadence: 'daily' | 'week' | 'biweek' | 'month'
  day_of_week: number | null
  day_of_month: number | null
  channel: string
  note: string
  enabled: boolean
  next_run: string | null
  last_run: string | null
  last_tx_id: number | null
  created_at: string
  updated_at: string
}

// ── 视觉模型配置 ──
export interface VisionConfig {
  base_url: string
  model: string
  has_key: boolean
}

// ── 截图解析结果 ──
export interface FundCandidate {
  code: string
  name: string
}

export interface ParsedTxItem {
  fund_name: string
  fund_code: string | null
  action: string
  date: string | null
  amount: number | null
  shares: number | null
  nav: number | null
  fee: number | null
  channel: string
  note: string
  is_t1: boolean
  code_status: 'exact' | 'multiple' | 'none'
  candidates: FundCandidate[]
}

export interface ParsedHoldingItem {
  fund_name: string
  fund_code: string | null
  shares: number | null
  market_value: number | null
  code_status: 'exact' | 'multiple' | 'none'
  candidates: FundCandidate[]
}

export interface ParseScreenshotResult {
  ok: boolean
  items: ParsedTxItem[] | ParsedHoldingItem[]
  error: string
}

// ── 持仓对账 ──
export interface ReconcileDiffItem {
  fund_code: string
  fund_name: string
  recorded_shares: number
  screenshot_shares: number
  delta: number
  status: 'buy' | 'sell' | 'ok' | 'new' | 'maybe_sold'
  suggested_tx: {
    fund_code: string
    action: string
    date: string | null
    amount: number | null
    shares: number
    nav: number | null
    fee: number
    channel: string
    note: string
    is_t1: boolean
  } | null
}

export interface ReconcileResponse {
  channel: string
  items: ReconcileDiffItem[]
}
