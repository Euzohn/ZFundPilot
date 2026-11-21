import { beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { LanguageProvider } from "@/i18n/LanguageContext"
import type {
  BenchmarkPoint,
  ChannelPnLPoint,
  CurvePoint,
  PortfolioSummary,
  Position,
} from "@/api/types"
import Returns from "./Returns"

const mocks = vi.hoisted(() => ({
  getSummary: vi.fn(),
  getPortfolioCurve: vi.fn(),
  getChannelPnl: vi.fn(),
  getPositions: vi.fn(),
  getPortfolioBenchmark: vi.fn(),
  getPreferences: vi.fn(),
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}))

// 捕获组合曲线图数据（基准合并回归）
const chartCapture = vi.hoisted(() => ({
  data: null as Record<string, string | number>[] | null,
}))

vi.mock("@/api/client", () => ({ api: mocks }))
vi.mock("sonner", () => ({ toast: mocks.toast }))
vi.mock("@/components/TpSlAlertsPanel", () => ({ default: () => null }))
vi.mock("recharts", async () => {
  const React = await import("react")
  return {
    ResponsiveContainer: ({ children }: { children?: React.ReactNode }) =>
      React.createElement("div", null, children),
    ComposedChart: ({ data }: { data?: unknown }) => {
      chartCapture.data = data as Record<string, string | number>[]
      return null
    },
    BarChart: () => null,
    Bar: () => null,
    Line: () => null,
    Area: () => null,
    Cell: () => null,
    XAxis: () => null,
    YAxis: () => null,
    CartesianGrid: () => null,
    Tooltip: () => null,
    Legend: () => null,
    ReferenceLine: () => null,
  }
})

const summary: PortfolioSummary = {
  total_cost: 9000,
  total_value: 10200,
  unrealized_pnl: 1200,
  realized_pnl: 0,
  total_pnl: 1200,
  total_return: 0.1333,
  annualized_return: 0.1,
  total_buy: 9000,
  total_sell: 0,
  total_dividend: 0,
  holding_count: 1,
  max_single_weight: 1,
  max_single_name: "基金000001",
  as_of_date: "2026-01-06",
  daily_pnl: 200,
  daily_return: 0.02,
  week_pnl: 200,
  week_return: 0.02,
  month_pnl: 200,
  month_return: 0.02,
  year_pnl: 200,
  year_return: 0.02,
}

const curve: CurvePoint[] = [
  { date: "2026-01-05", total_value: 10000, invested_cost: 9000, total_return: 0.111 },
  { date: "2026-01-06", total_value: 10200, invested_cost: 9000, total_return: 0.133 },
]

const channelPnl: ChannelPnLPoint[] = [
  { date: "2026-01-05", 支付宝: 100 },
  { date: "2026-01-06", 支付宝: -50 },
]

const benchmark: BenchmarkPoint[] = [
  { date: "2026-01-05", "000300": 0.01 },
  { date: "2026-01-06", "000300": 0.02 },
]

function position(overrides: Partial<Position> = {}): Position {
  return {
    fund_code: "000001",
    fund_name: "基金000001",
    fund_type: "股票型",
    sector: "",
    channel: "支付宝",
    tracking_index: "",
    risk_level: "",
    held_shares: 1000,
    total_cost: 9000,
    avg_cost_nav: 9,
    latest_nav: 10.2,
    latest_date: "2026-01-06",
    market_value: 10200,
    unrealized_pnl: 1200,
    realized_pnl: 0,
    return_rate: 0.133,
    annualized_return: 0.1,
    weight: 1,
    buy_count: 1,
    sell_count: 0,
    dividend_count: 0,
    dividend_total: 0,
    total_pnl: 1200,
    is_open: true,
    ...overrides,
  }
}

function renderPage() {
  return render(
    <LanguageProvider>
      <Returns />
    </LanguageProvider>,
  )
}

beforeEach(() => {
  chartCapture.data = null
  mocks.getSummary.mockReset().mockResolvedValue(summary)
  mocks.getPortfolioCurve.mockReset().mockResolvedValue(curve)
  mocks.getChannelPnl.mockReset().mockResolvedValue(channelPnl)
  mocks.getPositions.mockReset().mockResolvedValue([])
  mocks.getPortfolioBenchmark.mockReset().mockResolvedValue(benchmark)
  mocks.getPreferences.mockReset().mockResolvedValue({})
  mocks.toast.success.mockReset()
  mocks.toast.error.mockReset()
  mocks.toast.warning.mockReset()
})

describe("Returns", () => {
  it("组合曲线失败时展示 ErrorState 而非「暂无数据」，重试可恢复", async () => {
    mocks.getPortfolioCurve.mockRejectedValue(new Error("曲线请求失败"))
    renderPage()

    expect(await screen.findByText("曲线请求失败")).toBeInTheDocument()
    expect(screen.queryByText(/净值历史不足/)).not.toBeInTheDocument()

    mocks.getPortfolioCurve.mockResolvedValue(curve)
    fireEvent.click(screen.getByRole("button", { name: "重试" }))

    await waitFor(() => expect(chartCapture.data?.length).toBe(2))
    expect(screen.queryByText("曲线请求失败")).not.toBeInTheDocument()
  })

  it("持仓失败时不能伪装成「暂无持仓数据」，重试可恢复", async () => {
    mocks.getPositions.mockRejectedValue(new Error("持仓请求失败"))
    renderPage()

    expect(await screen.findByText("持仓请求失败")).toBeInTheDocument()
    expect(screen.queryByText("暂无持仓数据")).not.toBeInTheDocument()

    mocks.getPositions.mockResolvedValue([position()])
    fireEvent.click(screen.getByRole("button", { name: "重试" }))

    expect(await screen.findByText("基金000001")).toBeInTheDocument()
    expect(screen.queryByText("持仓请求失败")).not.toBeInTheDocument()
  })

  it("渠道收益失败时展示 ErrorState 而非隐藏区块，重试可恢复", async () => {
    mocks.getChannelPnl.mockRejectedValue(new Error("渠道收益请求失败"))
    renderPage()

    expect(await screen.findByText("渠道收益请求失败")).toBeInTheDocument()
    expect(screen.queryByText("收益波动")).not.toBeInTheDocument()

    mocks.getChannelPnl.mockResolvedValue(channelPnl)
    fireEvent.click(screen.getByRole("button", { name: "重试" }))

    expect(await screen.findByText("收益波动")).toBeInTheDocument()
    expect(screen.queryByText("渠道收益请求失败")).not.toBeInTheDocument()
  })

  it("基准请求失败时 toast 提示并保留已加载的基准曲线", async () => {
    renderPage()

    await waitFor(() => expect(mocks.getPortfolioBenchmark).toHaveBeenCalledWith(["000300"]))
    // 首次加载成功：曲线行已合并沪深300基准
    await waitFor(() => expect(chartCapture.data?.[0]?.["000300"]).toBe(0.01))

    // 追加基准时请求失败
    mocks.getPortfolioBenchmark.mockRejectedValueOnce(new Error("benchmark down"))
    fireEvent.click(screen.getByRole("button", { name: "上证指数" }))

    await waitFor(() =>
      expect(mocks.getPortfolioBenchmark).toHaveBeenCalledWith(["000300", "000001"]),
    )
    await waitFor(() => expect(mocks.toast.error).toHaveBeenCalledWith("加载失败"))
    // 旧实现会 setBenchmarkData(null) 清掉已有基准；现在应保留
    await waitFor(() => expect(chartCapture.data?.[0]?.["000300"]).toBe(0.01))
    expect(mocks.toast.success).not.toHaveBeenCalled()
  })
})