import { beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { LanguageProvider } from "@/i18n/LanguageContext"
import type { BacktestResult } from "@/api/types"
import Backtest from "./Backtest"

const mocks = vi.hoisted(() => ({
  runDcaBacktest: vi.fn(),
}))

// 捕获图表数据与渲染的曲线 dataKey（lumpsum 门控回归）
const chartCapture = vi.hoisted(() => ({
  data: null as { date: string }[] | null,
  keys: [] as string[],
}))

vi.mock("@/api/client", () => ({ api: mocks }))
vi.mock("recharts", async () => {
  const React = await import("react")
  return {
    ResponsiveContainer: ({ children }: { children?: React.ReactNode }) =>
      React.createElement("div", null, children),
    ComposedChart: ({ data, children }: { data?: unknown; children?: React.ReactNode }) => {
      chartCapture.data = data as { date: string }[]
      return React.createElement("div", null, children)
    },
    Line: ({ dataKey }: { dataKey?: string }) => {
      if (dataKey) chartCapture.keys.push(dataKey)
      return null
    },
    Area: ({ dataKey }: { dataKey?: string }) => {
      if (dataKey) chartCapture.keys.push(dataKey)
      return null
    },
    XAxis: () => null,
    YAxis: () => null,
    CartesianGrid: () => null,
    Tooltip: () => null,
    Legend: () => null,
  }
})

function result(
  code: string,
  strategy: "dca" | "lumpsum",
  firstDate: string,
): BacktestResult {
  const [y, m] = firstDate.split("-").map(Number)
  const dates = [0, 1, 2].map((i) => {
    const mm = m + i
    return `${y}-${String(mm).padStart(2, "0")}-05`
  })
  return {
    fund_code: code,
    fund_name: `基金${code}`,
    strategy,
    period_start: dates[0],
    period_end: dates[2],
    cadence: "month",
    amount_per_period: 1000,
    total_periods: 3,
    invested_capital: 3000,
    total_fees: 3,
    final_value: 3100,
    redemption_fee: 0,
    net_final_value: 3100,
    total_return: 0.033,
    annualized_return: 0.03,
    max_drawdown: -0.01,
    sharpe_ratio: 1.1,
    curve: dates.map((date, i) => ({
      date,
      invested: 1000 * (i + 1),
      value: 1000 * (i + 1) + 50,
      return: 0.01 * (i + 1),
    })),
    periods_detail: [
      {
        planned_date: dates[0],
        actual_date: dates[0],
        nav: 1,
        amount: 1000,
        fee: 1,
        invested: 1000,
        shares: 999,
        cumulative_shares: 999,
        cumulative_invested: 1000,
      },
    ],
  }
}

function renderPage() {
  return render(
    <MemoryRouter>
      <LanguageProvider>
        <Backtest />
      </LanguageProvider>
    </MemoryRouter>,
  )
}

function addCodesAndRun(codes: string) {
  fireEvent.change(screen.getByPlaceholderText("输入6位基金代码，逗号或空格分隔"), {
    target: { value: codes },
  })
  fireEvent.click(screen.getByRole("button", { name: "新增" }))
  fireEvent.click(screen.getByRole("button", { name: "开始回测" }))
}

beforeEach(() => {
  chartCapture.data = null
  chartCapture.keys = []
  mocks.runDcaBacktest.mockReset()
})

describe("Backtest", () => {
  it("新结果不含选中基金时重置 selectedFund，图表/明细回退到第一个基金", async () => {
    mocks.runDcaBacktest
      .mockResolvedValueOnce({
        ok: true,
        message: "",
        results: [result("000001", "dca", "2026-01"), result("000002", "dca", "2026-04")],
      })
      .mockResolvedValueOnce({
        ok: true,
        message: "",
        results: [result("000003", "dca", "2026-07")],
      })
    renderPage()

    addCodesAndRun("000001,000002")
    await waitFor(() => expect(mocks.runDcaBacktest).toHaveBeenCalledTimes(1))

    // 在图表下拉中选中基金 B（曲线变为 B 的日期）
    const select = await screen.findByDisplayValue("000001 基金000001")
    fireEvent.change(select, { target: { value: "000002" } })
    await waitFor(() => expect(chartCapture.data?.[0]?.date).toBe("2026-04-05"))

    // 移除旧基金，改用另一组基金重新回测（新结果只有 000003）
    while (screen.queryAllByTitle("移除").length > 0) {
      fireEvent.click(screen.queryAllByTitle("移除")[0])
    }
    addCodesAndRun("000003")
    await waitFor(() => expect(mocks.runDcaBacktest).toHaveBeenCalledTimes(2))

    // 旧实现 selectedFund 停留在 000002 → chartData 为空且无法恢复
    await waitFor(() => expect(chartCapture.data?.[0]?.date).toBe("2026-07-05"))
    expect(screen.queryByText("数据不足")).not.toBeInTheDocument()

    // 每期明细同样回退到新基金（planned_date/actual_date 两列同值）
    fireEvent.mouseDown(screen.getByRole("tab", { name: "每期明细" }))
    await waitFor(() => expect(screen.getAllByText("2026-07-05").length).toBeGreaterThan(0), { timeout: 3000 })
    expect(screen.queryByText("无明细")).not.toBeInTheDocument()
  })

  it("新结果仍含选中基金时保留选择", async () => {
    const both = {
      ok: true,
      message: "",
      results: [result("000001", "dca", "2026-01"), result("000002", "dca", "2026-04")],
    }
    mocks.runDcaBacktest.mockResolvedValue(both)
    renderPage()

    addCodesAndRun("000001,000002")
    await waitFor(() => expect(mocks.runDcaBacktest).toHaveBeenCalledTimes(1))
    const select = await screen.findByDisplayValue("000001 基金000001")
    fireEvent.change(select, { target: { value: "000002" } })
    await waitFor(() => expect(chartCapture.data?.[0]?.date).toBe("2026-04-05"))

    fireEvent.click(screen.getByRole("button", { name: "开始回测" }))
    await waitFor(() => expect(mocks.runDcaBacktest).toHaveBeenCalledTimes(2))

    expect(screen.getByDisplayValue("000002 基金000002")).toBeInTheDocument()
    await waitFor(() => expect(chartCapture.data?.[0]?.date).toBe("2026-04-05"))
  })

  it("lumpsum 曲线按结果内容渲染，而非表单勾选", async () => {
    mocks.runDcaBacktest
      .mockResolvedValueOnce({
        ok: true,
        message: "",
        results: [result("000001", "dca", "2026-01"), result("000001", "lumpsum", "2026-01")],
      })
      .mockResolvedValueOnce({
        ok: true,
        message: "",
        results: [result("000001", "dca", "2026-01")],
      })
    renderPage()

    // 默认勾选对比一次性投入，结果含 lumpsum → 曲线渲染
    addCodesAndRun("000001")
    await waitFor(() => expect(mocks.runDcaBacktest).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(chartCapture.keys).toContain("lump_value"))

    // 回测后取消勾选（未重新运行）：结果仍含 lumpsum，曲线不应消失
    chartCapture.keys = []
    fireEvent.click(screen.getByRole("checkbox", { name: "对比一次性投入" }))
    await waitFor(() => expect(chartCapture.keys.length).toBeGreaterThan(0))
    expect(chartCapture.keys).toContain("lump_value")

    // 以不勾选重新回测：结果不含 lumpsum → 曲线不渲染
    chartCapture.keys = []
    fireEvent.click(screen.getByRole("button", { name: "开始回测" }))
    await waitFor(() => expect(mocks.runDcaBacktest).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(chartCapture.keys.length).toBeGreaterThan(0))
    expect(chartCapture.keys).not.toContain("lump_value")

    // 运行后再勾选（未重新运行）：不应渲染全 null 的 lumpsum 曲线
    chartCapture.keys = []
    fireEvent.click(screen.getByRole("checkbox", { name: "对比一次性投入" }))
    await waitFor(() => expect(chartCapture.keys.length).toBeGreaterThan(0))
    expect(chartCapture.keys).not.toContain("lump_value")
  })
})