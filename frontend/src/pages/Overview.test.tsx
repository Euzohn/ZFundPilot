import { beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import type { ReactNode } from "react"
import { LanguageProvider } from "@/i18n/LanguageContext"
import type { DistributionItem, EstimateSummary, PortfolioSummary } from "@/api/types"
import Overview from "./Overview"

const mocks = vi.hoisted(() => ({
  getSummary: vi.fn(),
  getDistribution: vi.fn(),
  getEstimate: vi.fn(),
}))

vi.mock("@/api/client", () => ({ api: mocks }))

// jsdom 无布局尺寸，recharts 用桩组件替代，仅验证图表是否渲染
vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children?: ReactNode }) => <div data-testid="chart">{children}</div>,
  PieChart: () => <div data-testid="pie" />,
  BarChart: () => <div data-testid="bar" />,
  Pie: () => null,
  Cell: () => null,
  Bar: () => null,
  XAxis: () => null,
  YAxis: () => null,
  Tooltip: () => null,
  CartesianGrid: () => null,
}))

function summary(overrides: Partial<PortfolioSummary> = {}): PortfolioSummary {
  return {
    total_cost: 1000,
    total_value: 1100,
    unrealized_pnl: 100,
    realized_pnl: 0,
    total_pnl: 100,
    total_return: 0.1,
    annualized_return: null,
    total_buy: 1000,
    total_sell: 0,
    total_dividend: 0,
    holding_count: 1,
    max_single_weight: 1,
    max_single_name: "易方达蓝筹精选",
    as_of_date: "2026-11-20",
    daily_pnl: 10,
    daily_return: 0.01,
    week_pnl: 20,
    week_return: 0.02,
    month_pnl: 30,
    month_return: 0.03,
    year_pnl: 40,
    year_return: 0.04,
    ...overrides,
  }
}

function estimateOk(): EstimateSummary {
  return {
    funds: [{
      fund_code: "005827",
      fund_name: "易方达蓝筹精选",
      held_shares: 100,
      dwjz: 1.5,
      gsz: 1.52,
      gszzl: 1.33,
      gztime: "2026-11-20 15:00",
      estimated_pnl: 2,
      prev_value: 150,
      ok: true,
      message: "",
      code: "",
    }],
    total_estimated_pnl: 12.34,
    estimated_return: 0.0123,
    gztime: "2026-11-20 15:00",
  }
}

function renderPage() {
  return render(
    <MemoryRouter>
      <LanguageProvider>
        <Overview />
      </LanguageProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  mocks.getSummary.mockReset().mockResolvedValue(summary())
  mocks.getDistribution.mockReset().mockResolvedValue([])
  mocks.getEstimate.mockReset().mockResolvedValue(estimateOk())
})

describe("Overview 分布错误处理", () => {
  it("单个分布请求失败时展示错误与重试，不影响整页；重试成功后渲染图表", async () => {
    mocks.getDistribution.mockImplementation((field: string) => {
      if (field === "sector") return Promise.reject(new Error("板块分布加载失败"))
      return Promise.resolve([])
    })
    renderPage()

    // 错误局部展示，页面其余部分正常
    expect(await screen.findByText("板块分布加载失败")).toBeInTheDocument()
    expect(screen.getByText("累计盈亏")).toBeInTheDocument()

    mocks.getDistribution.mockResolvedValue([{ sector: "消费", market_value: 1000, weight: 1 }] satisfies DistributionItem[])
    fireEvent.click(screen.getByRole("button", { name: "重试" }))

    await waitFor(() => expect(screen.queryByText("板块分布加载失败")).not.toBeInTheDocument())
    await waitFor(() => expect(screen.getAllByTestId("chart").length).toBeGreaterThan(0))
    expect(mocks.getDistribution.mock.calls.filter((c) => c[0] === "sector")).toHaveLength(2)
  })
})

describe("Overview 估算错误处理", () => {
  it("估算失败展示可重试错误而非静默 —，重试成功后显示估算盈亏", async () => {
    mocks.getEstimate.mockRejectedValueOnce(new Error("估算接口超时")).mockResolvedValue(estimateOk())
    renderPage()

    expect(await screen.findByText("估算接口超时")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "重试" }))

    expect(await screen.findByText("+¥12.34")).toBeInTheDocument()
    expect(screen.queryByText("估算接口超时")).not.toBeInTheDocument()
    expect(mocks.getEstimate).toHaveBeenCalledTimes(2)
  })
})

describe("Overview 汇总错误处理", () => {
  it("汇总失败整页 ErrorState，重试后恢复", async () => {
    mocks.getSummary.mockRejectedValueOnce(new Error("汇总加载失败")).mockResolvedValue(summary())
    renderPage()

    expect(await screen.findByText("汇总加载失败")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: "重试" }))

    expect(await screen.findByText("累计盈亏")).toBeInTheDocument()
  })
})