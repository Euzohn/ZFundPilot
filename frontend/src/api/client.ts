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
  downloadTemplate: () => window.open(`${BASE}/csv/template`),
  exportCsv: () => window.open(`${BASE}/csv/export`),
  parseCsv: async (file: File): Promise<CSVParseResult> => {
    const form = new FormData()
    form.append("file", file)
    const res = await fetch(`${BASE}/csv/parse`, { method: "POST", body: form })
    return res.json()
  },
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
