export interface Fund {
  fund_code: string
  fund_name: string
  fund_type: string
  sector: string
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
}

export interface Position {
  fund_code: string
  fund_name: string
  fund_type: string
  sector: string
  channel: string
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
}

export interface CurvePoint {
  date: string
  total_value: number
  invested_cost: number
  total_return: number
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
  title: string
  detail: string
}

export interface Advice {
  category: string
  text: string
}

export interface FetchResult {
  fund_code: string
  ok: boolean
  written: number
  message: string
  latest_date: string | null
  latest_nav: number | null
}

export interface FundMeta {
  fund_code: string
  fund_name: string
  fund_type: string
  sector: string
  ok: boolean
  message: string
}

export interface LatestNav {
  fund_code: string
  date: string
  nav: number
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
