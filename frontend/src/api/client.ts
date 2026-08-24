import type {
  Advice,
  AuditLog,
  AutoInvestPlan,
  BacktestResult,
  ChannelPnLPoint,
  CompareResponse,
  CurvePoint,
  BenchmarkPoint,
  DistributionItem,
  DividendAlert,
  DividendEvent,
  EstimateSummary,
  FundEstimate,
  FundMeta,
  FilterResponse,
  LatestNav,
  NavUpdateStatus,
  PortfolioSummary,
  Position,
  RiskReport,
  Transaction,
  CSVParseResult,
  WatchlistItem,
  AIUsageStats,
  AIUsageDaily,
  FeeRatesResponse,
  CalcFeeResponse,
  FundHoldings,
  FundRanking,
  FundProfile,
  KeywordMaps,
  SchedulerStatus,
  TpSlConfig,
} from "./types"
import { getToken, clearToken } from "@/lib/auth"
import { getCurrentLang } from "@/i18n/LanguageContext"

const BASE = "/api"

const ERR_401 = { zh: "未登录或登录已过期", en: "Not authenticated or session expired" }

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const token = getToken()
  const headers: Record<string, string> = { "Content-Type": "application/json" }
  if (token) headers["Authorization"] = `Bearer ${token}`

  const res = await fetch(`${BASE}${url}`, {
    ...options,
    headers: { ...headers, ...options?.headers },
  })

  if (res.status === 401) {
    clearToken()
    window.location.reload()
    throw new Error(ERR_401[getCurrentLang()])
  }
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    let msg = text || `${res.status}`
    try { const j = JSON.parse(text); if (j.detail) msg = j.detail } catch { /* not json */ }
    throw new Error(msg)
  }
  return res.json()
}

async function downloadWithAuth(url: string, filename: string) {
  const token = getToken()
  const headers: Record<string, string> = {}
  if (token) headers["Authorization"] = `Bearer ${token}`
  const res = await fetch(`${BASE}${url}`, { headers })
  if (!res.ok) throw new Error(await res.text().catch(() => res.statusText))
  const blob = await res.blob()
  const a = document.createElement("a")
  a.href = URL.createObjectURL(blob)
  a.download = filename
  a.click()
  URL.revokeObjectURL(a.href)
}

export const api = {
  // Auth
  getAuthStatus: () => request<{ required: boolean; version: string }>("/auth/status"),
  getMe: () => request<{ username: string }>("/auth/me"),
  login: (username: string, password: string) =>
    request<{ ok: boolean; token: string; message: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  changePassword: (currentPassword: string, newPassword: string) =>
    request<{ ok: boolean; message: string }>("/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    }),
  changeUsername: (currentPassword: string, newUsername: string) =>
    request<{ ok: boolean; message: string }>("/auth/change-username", {
      method: "POST",
      body: JSON.stringify({ current_password: currentPassword, new_username: newUsername }),
    }),

  // AI Config
  getAIConfig: () =>
    request<{ base_url: string; model: string; has_key: boolean; web_search: boolean; custom_prompt: string }>("/settings/ai"),
  updateAIConfig: (base_url: string, api_key: string, model: string, web_search: boolean, custom_prompt: string = "") =>
    request<{ ok: boolean }>("/settings/ai", {
      method: "PUT",
      body: JSON.stringify({ base_url, api_key, model, web_search, custom_prompt }),
    }),

  // AI Usage
  getAIUsage: () => request<AIUsageStats>("/ai/usage"),

  // AI System Prompt (build once per conversation, reuse)
  getSystemPrompt: (includeContext?: boolean) =>
    request<{ system_prompt: string }>(`/ai/system-prompt?include_context=${includeContext ?? true}`),

  // AI Connection Test
  testAIConnection: () =>
    request<{ ok: boolean; provider?: string; model?: string; has_search?: boolean; error?: string }>("/ai/test", { method: "POST" }),

  // AI Usage Daily (for sparkline)
  getAIUsageDaily: (days = 7) => request<AIUsageDaily[]>(`/ai/usage/daily?days=${days}`),

  // AI Chat (SSE streaming — bypasses standard request() wrapper)
  streamChat: async (
    messages: { role: string; content: string }[],
    onChunk: (data: { content?: string; status?: string; error?: string; done?: boolean; usage?: { prompt: number; completion: number; total: number } }) => void,
  ) => {
    const token = getToken()
    const headers: Record<string, string> = { "Content-Type": "application/json" }
    if (token) headers["Authorization"] = `Bearer ${token}`

    const res = await fetch(`${BASE}/ai/chat`, {
      method: "POST",
      headers,
      body: JSON.stringify({ messages }),
    })

    if (res.status === 401) {
      clearToken()
      window.location.reload()
      throw new Error(ERR_401[getCurrentLang()])
    }
    if (!res.ok) {
      throw new Error(await res.text().catch(() => res.statusText))
    }

    const reader = res.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ""

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      const lines = buffer.split("\n")
      buffer = lines.pop() || ""

      for (const line of lines) {
        if (line.startsWith("data: ")) {
          const data = line.slice(6).trim()
          if (data === "[DONE]") return
          try {
            onChunk(JSON.parse(data))
          } catch { /* skip malformed */ }
        }
      }
    }
  },

  // Summary
  getSummary: () => request<PortfolioSummary>("/summary"),
  getDistribution: (field: string) =>
    request<DistributionItem[]>(`/distribution/${field}`),

  // Positions
  getPositions: (includeClosed = false) =>
    request<Position[]>(`/positions?include_closed=${includeClosed}`),

  // Transactions
  getTransactions: () => request<Transaction[]>("/transactions"),
  getTransactionsByFund: (code: string) =>
    request<Transaction[]>(`/transactions?fund_code=${encodeURIComponent(code)}`),
  addTransaction: (tx: Transaction) =>
    request<{ id: number }>("/transactions", {
      method: "POST",
      body: JSON.stringify(tx),
    }),
  deleteTransaction: (id: number) =>
    request<{ ok: boolean }>(`/transactions/${id}`, { method: "DELETE" }),
  updateTransaction: (id: number, tx: Transaction) =>
    request<{ ok: boolean }>(`/transactions/${id}`, {
      method: "PUT",
      body: JSON.stringify(tx),
    }),
  deleteAllTransactions: () =>
    request<{ ok: boolean }>("/transactions", { method: "DELETE" }),

  // Funds
  getFunds: () => request<FundMeta[]>("/funds"),
  getFund: (code: string) => request<FundMeta>(`/funds/${encodeURIComponent(code)}`),
  fetchFundMeta: (code: string) =>
    request<FundMeta>(`/funds/${code}/fetch`, { method: "POST" }),

  // Fee rates
  getFundFeeRates: (code: string) =>
    request<FeeRatesResponse>(`/funds/${encodeURIComponent(code)}/fee-rates`),
  getFundHoldings: (code: string) =>
    request<FundHoldings>(`/funds/${encodeURIComponent(code)}/holdings`),
  getFundRanking: (code: string) =>
    request<FundRanking>(`/funds/${encodeURIComponent(code)}/ranking`),
  getFundProfile: (code: string) =>
    request<FundProfile>(`/funds/${encodeURIComponent(code)}/profile`),
  calcFundFee: (code: string, params: { action: string; amount?: number; shares?: number; date?: string }) => {
    const q = new URLSearchParams()
    q.set("action", params.action)
    if (params.amount != null) q.set("amount", String(params.amount))
    if (params.shares != null) q.set("shares", String(params.shares))
    if (params.date) q.set("date", params.date)
    return request<CalcFeeResponse>(`/funds/${encodeURIComponent(code)}/calc-fee?${q.toString()}`)
  },

  // NAV
  updateNav: () => request<{ ok: boolean; message: string; total: number }>("/nav/update", { method: "POST" }),
  getNavUpdateStatus: () => request<NavUpdateStatus>("/nav/update/status"),
  getLatestNavs: () => request<LatestNav[]>("/nav/latest"),
  getNavHistory: (code: string) =>
    request<{ fund_code: string; date: string; nav: number; accumulated_nav: number | null; source: string }[]>(`/nav/${encodeURIComponent(code)}`),
  getNavForDate: (code: string, date: string) =>
    request<{ date: string; nav: number }[]>(`/nav/${encodeURIComponent(code)}?date=${date}`),

  // Portfolio curve
  getPortfolioCurve: () => request<CurvePoint[]>("/portfolio/curve"),
  getPortfolioBenchmark: (indices: string[]) =>
    request<BenchmarkPoint[]>(`/portfolio/benchmark?indices=${indices.join(",")}`),
  getChannelPnl: () => request<ChannelPnLPoint[]>("/portfolio/channel-pnl"),

  // Risk & Rebalance
  getRiskReport: () => request<RiskReport>("/risk"),
  getRebalanceAdvice: () => request<Advice[]>("/rebalance"),

  // CSV
  downloadTemplate: () => downloadWithAuth("/csv/template", "transactions_template.csv"),
  exportCsv: () => {
    const now = new Date()
    const pad = (n: number) => String(n).padStart(2, "0")
    const ts = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}`
    return downloadWithAuth("/csv/export", `transactions_${ts}.csv`)
  },
  exportZip: () => {
    const now = new Date()
    const pad = (n: number) => String(n).padStart(2, "0")
    const ts = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}`
    return downloadWithAuth("/export/zip", `zfundpilot_backup_${ts}.zip`)
  },
  parseCsv: async (file: File): Promise<CSVParseResult> => {
    const form = new FormData()
    form.append("file", file)
    const token = getToken()
    const headers: Record<string, string> = {}
    if (token) headers["Authorization"] = `Bearer ${token}`
    const res = await fetch(`${BASE}/csv/parse`, { method: "POST", body: form, headers })
    if (res.status === 401) {
      clearToken()
      window.location.reload()
      throw new Error(ERR_401[getCurrentLang()])
    }
    if (!res.ok) throw new Error(await res.text().catch(() => res.statusText))
    return res.json()
  },
  resetSectors: () => request<{ reset: number }>("/sectors/reset", { method: "POST" }),

  confirmImport: (transactions: Transaction[], clearExisting: boolean, fetchMeta: boolean) =>
    request<{ imported: number }>("/csv/import", {
      method: "POST",
      body: JSON.stringify({
        transactions,
        clear_existing: clearExisting,
        fetch_meta: fetchMeta,
      }),
    }),

  // Preferences
  getPreferences: () => request<Record<string, string>>("/preferences"),
  savePreferences: (body: { channels?: string; channel_colors?: string; color_theme?: string }) =>
    request<{ ok: boolean }>("/preferences", {
      method: "PUT",
      body: JSON.stringify({
        channels: body.channels ?? "",
        channel_colors: body.channel_colors ?? "",
        color_theme: body.color_theme ?? "",
      }),
    }),

  // Keyword maps
  getKeywordMaps: () => request<KeywordMaps>("/keyword-maps"),
  saveKeywordMaps: (type_custom: string, sector_custom: string) =>
    request<{ ok: boolean }>("/keyword-maps", {
      method: "PUT",
      body: JSON.stringify({ type_custom, sector_custom }),
    }),

  // Scheduler
  getSchedulerStatus: () => request<SchedulerStatus>("/scheduler/status"),
  toggleScheduler: (enabled: boolean) =>
    request<SchedulerStatus>("/scheduler/toggle", {
      method: "PUT",
      body: JSON.stringify({ enabled }),
    }),
  setSchedulerCron: (cron: string) =>
    request<SchedulerStatus>("/scheduler/cron", {
      method: "PUT",
      body: JSON.stringify({ cron }),
    }),

  // Estimate (real-time fundgz)
  getEstimate: () => request<EstimateSummary>("/estimate"),
  getFundEstimate: (code: string) =>
    request<FundEstimate>(`/funds/${encodeURIComponent(code)}/estimate`),

  // Audit log
  getAuditLogs: (limit = 100) =>
    request<AuditLog[]>(`/audit?limit=${limit}`),

  // Fund filter
  filterFunds: (params: { types?: string[]; sectors?: string[]; keyword?: string; limit?: number; offset?: number; with_metrics?: boolean }) =>
    request<FilterResponse>("/funds/filter", {
      method: "POST",
      body: JSON.stringify(params),
    }),

  // Fund compare
  compareFunds: (codes: string[]) =>
    request<CompareResponse>("/funds/compare", {
      method: "POST",
      body: JSON.stringify({ codes }),
    }),

  // DCA backtest
  runDcaBacktest: (params: {
    fund_codes: string[]
    start_date: string
    end_date: string
    amount_per_period: number
    cadence: string
    include_lumpsum: boolean
  }) =>
    request<{ results: BacktestResult[]; ok: boolean; message: string }>("/backtest/dca", {
      method: "POST",
      body: JSON.stringify(params),
    }),

  // Auto invest plans
  getAutoInvestPlans: () => request<AutoInvestPlan[]>("/auto-invest/plans"),
  createAutoInvestPlan: (plan: {
    fund_code: string
    amount: number
    cadence: string
    day_of_week?: number | null
    day_of_month?: number | null
    channel?: string
    note?: string
  }) => request<{ id: number }>("/auto-invest/plans", {
    method: "POST",
    body: JSON.stringify(plan),
  }),
  updateAutoInvestPlan: (id: number, plan: {
    fund_code: string
    amount: number
    cadence: string
    day_of_week?: number | null
    day_of_month?: number | null
    channel?: string
    note?: string
  }) => request<{ ok: boolean }>(`/auto-invest/plans/${id}`, {
    method: "PUT",
    body: JSON.stringify(plan),
  }),
  deleteAutoInvestPlan: (id: number) =>
    request<{ ok: boolean }>(`/auto-invest/plans/${id}`, { method: "DELETE" }),
  toggleAutoInvestPlan: (id: number, enabled: boolean) =>
    request<{ ok: boolean }>(`/auto-invest/plans/${id}/toggle`, {
      method: "PUT",
      body: JSON.stringify({ enabled }),
    }),
  executeAutoInvestPlan: (id: number) =>
    request<{ ok: boolean; tx_id?: number }>(`/auto-invest/plans/${id}/execute`, {
      method: "POST",
    }),

  // Watchlist
  getWatchlist: () => request<WatchlistItem[]>("/watchlist"),
  addToWatchlist: (code: string, note?: string, groupName?: string) =>
    request<{ ok: boolean; code: string }>("/watchlist", {
      method: "POST",
      body: JSON.stringify({ code, note: note ?? "", group_name: groupName ?? "" }),
    }),
  updateWatchlistGroup: (code: string, groupName: string) =>
    request<{ ok: boolean; code: string }>(`/watchlist/${encodeURIComponent(code)}/group`, {
      method: "PUT",
      body: JSON.stringify({ group_name: groupName }),
    }),
  removeFromWatchlist: (code: string) =>
    request<{ ok: boolean; code: string }>(`/watchlist/${encodeURIComponent(code)}`, {
      method: "DELETE",
    }),

  // Dividend
  checkDividends: () => request<DividendEvent[]>("/dividends/check"),
  updateDividendMethod: (code: string, method: string) =>
    request<{ ok: boolean }>(`/funds/${encodeURIComponent(code)}/dividend-method`, {
      method: "PUT",
      body: JSON.stringify({ method }),
    }),
  getDividendAlerts: (status?: string) =>
    request<DividendAlert[]>(`/dividends/alerts${status ? `?status=${status}` : ""}`),
  getPendingAlertCount: (type?: string) =>
    request<{ count: number }>(`/alerts/count${type ? `?type=${type}` : ""}`),
  getPendingDividendAlertCount: () =>
    request<{ count: number }>("/dividends/alerts/count"),
  updateDividendAlert: (id: number, status: string, txId?: number) =>
    request<{ ok: boolean }>(`/dividends/alerts/${id}`, {
      method: "PUT",
      body: JSON.stringify({ status, tx_id: txId ?? null }),
    }),
  deleteDividendAlert: (id: number) =>
    request<{ ok: boolean }>(`/dividends/alerts/${id}`, { method: "DELETE" }),
  scanDividends: () =>
    request<{ found: number; new: number; cleaned: number }>("/dividends/scan", { method: "POST" }),
  toggleDividendAutoCheck: (enabled: boolean) =>
    request<SchedulerStatus>("/dividends/auto-check", {
      method: "PUT",
      body: JSON.stringify({ enabled }),
    }),

  // TP/SL Alerts
  getTpSlConfig: () => request<TpSlConfig>("/alerts/config"),
  updateTpSlConfig: (config: Partial<TpSlConfig>) =>
    request<TpSlConfig>("/alerts/config", {
      method: "PUT",
      body: JSON.stringify(config),
    }),
  getTpSlAlerts: (status?: string) =>
    request<DividendAlert[]>(`/alerts?type=tp_sl${status ? `&status=${status}` : ""}`),
  updateAlert: (id: number, status: string) =>
    request<{ ok: boolean }>(`/alerts/${id}`, {
      method: "PUT",
      body: JSON.stringify({ status }),
    }),
}
