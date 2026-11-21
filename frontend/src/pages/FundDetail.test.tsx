import { beforeEach, describe, expect, it, vi } from "vitest"
import type { ReactNode } from "react"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { LanguageProvider } from "@/i18n/LanguageContext"
import { CompareProvider } from "@/contexts/CompareContext"
import type { Fund, FundEstimate, Position, Transaction } from "@/api/types"
import FundDetail from "./FundDetail"

const mocks = vi.hoisted(() => ({
  getWatchlist: vi.fn(),
  getFund: vi.fn(),
  getPositions: vi.fn(),
  getTransactionsByFund: vi.fn(),
  getNavHistory: vi.fn(),
  getFundEstimate: vi.fn(),
  getFundHoldings: vi.fn(),
  getFundIndustryAllocation: vi.fn(),
  getFundRanking: vi.fn(),
  getFundProfile: vi.fn(),
  getFundXirr: vi.fn(),
  deleteTransaction: vi.fn(),
}))

vi.mock("@/api/client", () => ({ api: mocks }))

// 图表打桩：ComposedChart 把 data 的日期序列暴露出来，便于断言 useMemo 过滤结果
vi.mock("recharts", async () => {
  const React = await import("react")
  const stub = () => null
  return {
    ResponsiveContainer: ({ children }: { children?: ReactNode }) =>
      React.createElement("div", null, children),
    ComposedChart: ({ data }: { data?: { date: string }[] }) =>
      React.createElement(
        "div",
        { "data-testid": "nav-chart-dates" },
        JSON.stringify((data ?? []).map((d) => d.date)),
      ),
    LineChart: stub,
    PieChart: stub,
    Pie: stub,
    Line: stub,
    Bar: stub,
    Cell: stub,
    XAxis: stub,
    YAxis: stub,
    CartesianGrid: stub,
    Tooltip: stub,
    ReferenceLine: stub,
  }
})

function fund(): Fund {
  return {
    fund_code: "005827",
    fund_name: "测试基金",
    fund_type: "混合型",
    sector: "消费",
    tracking_index: "",
  }
}

function position(overrides: Partial<Position> = {}): Position {
  return {
    fund_code: "005827",
    fund_name: "测试基金",
    fund_type: "混合型",
    sector: "消费",
    channel: "支付宝",
    tracking_index: "",
    risk_level: "",
    held_shares: 1000,
    total_cost: 1000,
    avg_cost_nav: 1,
    latest_nav: 1.1,
    latest_date: "2026-01-02",
    market_value: 1100,
    unrealized_pnl: 100,
    realized_pnl: 0,
    return_rate: 0.1,
    annualized_return: null,
    weight: 1,
    buy_count: 1,
    sell_count: 0,
    dividend_count: 0,
    dividend_total: 0,
    total_pnl: 100,
    is_open: true,
    ...overrides,
  }
}

function tx(overrides: Partial<Transaction> = {}): Transaction {
  return {
    id: 7,
    fund_code: "005827",
    action: "buy",
    date: "2026-01-02",
    amount: 1000,
    shares: 900,
    nav: 1.1,
    fee: 1,
    channel: "支付宝",
    note: "",
    ...overrides,
  }
}

function estimate(overrides: Partial<FundEstimate> = {}): FundEstimate {
  return {
    fund_code: "005827",
    fund_name: "测试基金",
    jzrq: "",
    dwjz: 0,
    gsz: 0,
    gszzl: 0,
    gztime: "",
    ok: false,
    message: "",
    code: "",
    ...overrides,
  }
}

// 最近 n 天的本地日期序列（避免测试依赖固定"今天"）
function recentDates(n: number): string[] {
  const out: string[] = []
  const today = new Date()
  for (let i = n - 1; i >= 0; i--) {
    const d = new Date(today)
    d.setDate(today.getDate() - i)
    out.push(
      `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`,
    )
  }
  return out
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/fund/005827"]}>
      <LanguageProvider>
        <CompareProvider>
          <Routes>
            <Route path="/fund/:code" element={<FundDetail />} />
          </Routes>
        </CompareProvider>
      </LanguageProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  mocks.getWatchlist.mockReset().mockResolvedValue([])
  mocks.getFund.mockReset().mockResolvedValue(fund())
  mocks.getPositions.mockReset().mockResolvedValue([position()])
  mocks.getTransactionsByFund.mockReset().mockResolvedValue([])
  mocks.getNavHistory.mockReset().mockResolvedValue([])
  mocks.getFundEstimate.mockReset().mockResolvedValue(estimate())
  mocks.getFundHoldings.mockReset().mockResolvedValue({ ok: false })
  mocks.getFundIndustryAllocation.mockReset().mockResolvedValue({ ok: false })
  mocks.getFundRanking.mockReset().mockResolvedValue({ ok: false })
  mocks.getFundProfile.mockReset().mockResolvedValue({ ok: false })
  mocks.getFundXirr.mockReset().mockResolvedValue({ annualized_return: null })
  mocks.deleteTransaction.mockReset().mockResolvedValue(undefined)
})

describe("FundDetail", () => {
  it("自定义区间修改起止日期后图表数据随之更新（回归 useMemo 依赖缺失）", async () => {
    const dates = recentDates(30)
    mocks.getNavHistory.mockResolvedValue(dates.map((date, i) => ({ date, nav: 1 + i * 0.001 })))
    const { container } = renderPage()

    // 默认 1y 区间：全部 30 天都在图上
    const chart = await screen.findByTestId("nav-chart-dates")
    expect(chart.textContent).toBe(JSON.stringify(dates))

    fireEvent.click(screen.getByRole("button", { name: "自定义" }))
    const inputs = container.querySelectorAll<HTMLInputElement>('input[type="date"]')
    expect(inputs).toHaveLength(2)
    fireEvent.change(inputs[0], { target: { value: dates[10] } })
    fireEvent.change(inputs[1], { target: { value: dates[15] } })

    // 修改 customStart/customEnd 必须触发 memo 重算，区间过滤立即生效
    await waitFor(() =>
      expect(screen.getByTestId("nav-chart-dates").textContent).toBe(
        JSON.stringify(dates.slice(10, 16)),
      ),
    )
  })

  it("删除交易成功后同步刷新持仓与 XIRR（回归汇总指标不更新）", async () => {
    mocks.getTransactionsByFund.mockResolvedValue([tx()])
    mocks.getFundXirr.mockResolvedValue({ annualized_return: 0.12 })
    renderPage()

    fireEvent.click(await screen.findByTitle("删除"))
    const dialog = await screen.findByRole("alertdialog")
    fireEvent.click(within(dialog).getByRole("button", { name: "删除" }))

    await waitFor(() => expect(mocks.deleteTransaction).toHaveBeenCalledWith(7))
    await waitFor(() => expect(mocks.getPositions).toHaveBeenCalledTimes(2))
    expect(mocks.getFundXirr).toHaveBeenCalledTimes(2)
    expect(mocks.getTransactionsByFund).toHaveBeenCalledTimes(2)
  })

  it("无持仓且展示估算时，最新净值卡片 sub 不渲染字面量 null", async () => {
    mocks.getPositions.mockResolvedValue([])
    mocks.getFundEstimate.mockResolvedValue(
      estimate({ ok: true, jzrq: "2026-01-02", gsz: 1.2345, gszzl: 1.5, gztime: "2026-01-05 15:00" }),
    )
    renderPage()

    const sub = await screen.findByText(/估算 1\.2345/)
    expect(sub.textContent).toBe("估算 1.2345 1.50% · 01-05 15:00")
    expect(screen.queryByText(/null/)).not.toBeInTheDocument()
  })

  it("有持仓时最新净值卡片 sub 保留净值日期前缀", async () => {
    mocks.getFundEstimate.mockResolvedValue(
      estimate({ ok: true, jzrq: "2026-01-02", gsz: 1.2345, gszzl: 1.5, gztime: "2026-01-05 15:00" }),
    )
    renderPage()

    const sub = await screen.findByText(/^2026-01-02 · 估算/)
    expect(sub.textContent).toBe("2026-01-02 · 估算 1.2345 1.50% · 01-05 15:00")
  })

  it("删除进行中确认按钮禁用，重复点击不会发起第二次删除", async () => {
    let resolveDelete!: () => void
    mocks.deleteTransaction.mockImplementation(
      () => new Promise<void>((resolve) => { resolveDelete = resolve }),
    )
    mocks.getTransactionsByFund.mockResolvedValue([tx()])
    renderPage()

    fireEvent.click(await screen.findByTitle("删除"))
    const dialog = await screen.findByRole("alertdialog")
    fireEvent.click(within(dialog).getByRole("button", { name: "删除" }))

    await waitFor(() => expect(mocks.deleteTransaction).toHaveBeenCalledTimes(1))
    // 删除进行中：确认按钮禁用并显示"处理中..."，取消按钮同样禁用
    const processing = within(dialog).getByRole("button", { name: "处理中..." })
    expect(processing).toBeDisabled()
    expect(within(dialog).getByRole("button", { name: "取消" })).toBeDisabled()

    fireEvent.click(processing)
    expect(mocks.deleteTransaction).toHaveBeenCalledTimes(1)

    resolveDelete()
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument())
  })
})