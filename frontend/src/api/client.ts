import type {
  Advice,
  CurvePoint,
  DistributionItem,
  FetchResult,
  FundMeta,
  LatestNav,
  PortfolioSummary,
  Position,
  RiskReport,
  Transaction,
  CSVParseResult,
  AIUsageStats,
} from "./types"
import { getToken, clearToken } from "@/lib/auth"

const BASE = "/api"

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
    throw new Error("未登录或登录已过期")
  }
  if (!res.ok) {
    const msg = await res.text().catch(() => res.statusText)
    throw new Error(msg || `${res.status}`)
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
  getAuthStatus: () => request<{ required: boolean }>("/auth/status"),
  login: (password: string) =>
    request<{ ok: boolean; token: string; message: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ password }),
    }),
  changePassword: (currentPassword: string, newPassword: string) =>
    request<{ ok: boolean; message: string }>("/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    }),

  // AI Config
  getAIConfig: () =>
    request<{ base_url: string; model: string; has_key: boolean; web_search: boolean }>("/settings/ai"),
  updateAIConfig: (base_url: string, api_key: string, model: string, web_search: boolean) =>
    request<{ ok: boolean }>("/settings/ai", {
      method: "PUT",
      body: JSON.stringify({ base_url, api_key, model, web_search }),
    }),

  // AI Usage
  getAIUsage: () => request<AIUsageStats>("/ai/usage"),

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
      throw new Error("未登录或登录已过期")
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

  // NAV
  updateNav: () => request<FetchResult[]>("/nav/update", { method: "POST" }),
  getLatestNavs: () => request<LatestNav[]>("/nav/latest"),
  getNavHistory: (code: string) =>
    request<{ fund_code: string; date: string; nav: number; accumulated_nav: number | null; source: string }[]>(`/nav/${encodeURIComponent(code)}`),
  getNavForDate: (code: string, date: string) =>
    request<{ date: string; nav: number }[]>(`/nav/${encodeURIComponent(code)}?date=${date}`),

  // Portfolio curve
  getPortfolioCurve: () => request<CurvePoint[]>("/portfolio/curve"),

  // Risk & Rebalance
  getRiskReport: () => request<RiskReport>("/risk"),
  getRebalanceAdvice: () => request<Advice[]>("/rebalance"),

  // CSV
  downloadTemplate: () => downloadWithAuth("/csv/template", "transactions_template.csv"),
  exportCsv: () => downloadWithAuth("/csv/export", "my_transactions.csv"),
  parseCsv: async (file: File): Promise<CSVParseResult> => {
    const form = new FormData()
    form.append("file", file)
    const res = await fetch(`${BASE}/csv/parse`, { method: "POST", body: form })
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
}
