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

const BASE = "/api"

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  })
  if (!res.ok) {
    const msg = await res.text().catch(() => res.statusText)
    throw new Error(msg || `${res.status}`)
  }
  return res.json()
}

export const api = {
  // Summary
  getSummary: () => request<PortfolioSummary>("/summary"),
  getDistribution: (field: string) =>
    request<DistributionItem[]>(`/distribution/${field}`),

  // Positions
  getPositions: (includeClosed = false) =>
    request<Position[]>(`/positions?include_closed=${includeClosed}`),

  // Transactions
  getTransactions: () => request<Transaction[]>("/transactions"),
  addTransaction: (tx: Transaction) =>
    request<{ id: number }>("/transactions", {
      method: "POST",
      body: JSON.stringify(tx),
    }),
  deleteTransaction: (id: number) =>
    request<{ ok: boolean }>(`/transactions/${id}`, { method: "DELETE" }),
  deleteAllTransactions: () =>
    request<{ ok: boolean }>("/transactions", { method: "DELETE" }),

  // Funds
  getFunds: () => request<FundMeta[]>("/funds"),
  fetchFundMeta: (code: string) =>
    request<FundMeta>(`/funds/${code}/fetch`, { method: "POST" }),

  // NAV
  updateNav: () => request<FetchResult[]>("/nav/update", { method: "POST" }),
  getLatestNavs: () => request<LatestNav[]>("/nav/latest"),

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
