import { beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { LanguageProvider } from "@/i18n/LanguageContext"
import { CompareProvider } from "@/contexts/CompareContext"
import type { CompareResponse, FundCompareItem } from "@/api/types"
import FundCompare from "./FundCompare"

const mocks = vi.hoisted(() => ({
  compareFunds: vi.fn(),
}))

// 捕获 NavChart 传给 LineChart 的合并数据（x 轴并集回归）
const chartCapture = vi.hoisted(() => ({
  data: null as Record<string, string | number | null>[] | null,
}))

vi.mock("@/api/client", () => ({ api: mocks }))
vi.mock("recharts", async () => {
  const React = await import("react")
  return {
    ResponsiveContainer: ({ children }: { children?: React.ReactNode }) =>
      React.createElement("div", null, children),
    LineChart: ({ data, children }: { data?: unknown; children?: React.ReactNode }) => {
      chartCapture.data = data as Record<string, string | number | null>[]
      return React.createElement("div", null, children)
    },
    Line: () => null,
    XAxis: () => null,
    YAxis: () => null,
    Tooltip: () => null,
    CartesianGrid: () => null,
    Legend: () => null,
  }
})

function fund(code: string, overrides: Partial<FundCompareItem> = {}): FundCompareItem {
  return {
    code,
    name: `基金${code}`,
    type: "股票型",
    sector: "",
    inception_date: "2020-01-01",
    scale: null,
    manager: "",
    management_fee: null,
    custodian_fee: null,
    sales_fee: null,
    returns: { "1y": 0.1 },
    risk: { max_drawdown: -0.2, volatility: 0.15, sharpe: 1.2, calmar: 2.5, win_rate: 0.55 },
    latest_nav: 1.5,
    latest_date: "2026-01-03",
    ok: true,
    message: "",
    msg_code: "",
    ...overrides,
  }
}

function response(): CompareResponse {
  return {
    funds: [
      fund("000001"),
      fund("000002", {
        risk: { max_drawdown: -0.1, volatility: 0.1, sharpe: null, calmar: 0.8, win_rate: 0.5 },
      }),
    ],
    correlations: null,
    // 000002 比 000001 多一个早期日期（成立日/交易日历不同）
    nav_series: {
      "000001": [
        { date: "2026-01-02", value: 100 },
        { date: "2026-01-03", value: 101 },
      ],
      "000002": [
        { date: "2026-01-01", value: 100 },
        { date: "2026-01-02", value: 99 },
        { date: "2026-01-03", value: 102 },
      ],
    },
    ok: true,
    message: "",
    msg_code: "",
  }
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/compare?codes=000001,000002"]}>
      <LanguageProvider>
        <CompareProvider>
          <FundCompare />
        </CompareProvider>
      </LanguageProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  chartCapture.data = null
  mocks.compareFunds.mockReset().mockResolvedValue(response())
})

describe("FundCompare", () => {
  it("风险表按指标区分格式：sharpe/calmar 原样 2 位小数，其余百分比", async () => {
    renderPage()
    await waitFor(() => expect(mocks.compareFunds).toHaveBeenCalledWith(["000001", "000002"]))

    fireEvent.mouseDown(await screen.findByRole("tab", { name: "风险指标对比" }))

    // sharpe 1.2 / calmar 2.5 是无量纲比值，不能 ×100 加百分号
    expect(await screen.findByText("1.20")).toBeInTheDocument()
    expect(screen.getByText("2.50")).toBeInTheDocument()
    expect(screen.getByText("0.80")).toBeInTheDocument()
    expect(screen.queryByText("120.00%")).not.toBeInTheDocument()
    expect(screen.queryByText("250.00%")).not.toBeInTheDocument()
    // 小数收益率仍按百分比显示
    expect(screen.getByText("-20.00%")).toBeInTheDocument()
    expect(screen.getByText("15.00%")).toBeInTheDocument()
    expect(screen.getByText("55.00%")).toBeInTheDocument()
    // null 夏普显示占位符而不是 NaN
    expect(screen.getAllByText("—").length).toBeGreaterThan(0)
    expect(screen.queryByText("NaN")).not.toBeInTheDocument()
  })

  it("NavChart x 轴取所有基金日期并集（排序），缺失日期填 null", async () => {
    renderPage()
    await waitFor(() => expect(mocks.compareFunds).toHaveBeenCalled())

    fireEvent.mouseDown(await screen.findByRole("tab", { name: "净值走势" }))

    await waitFor(() => expect(chartCapture.data).not.toBeNull())
    const rows = chartCapture.data!
    // 旧实现只取第一只基金的日期，会丢掉 000002 的 2026-01-01
    expect(rows.map((r) => r.date)).toEqual(["2026-01-01", "2026-01-02", "2026-01-03"])
    expect(rows[0]["000001"]).toBeNull()
    expect(rows[0]["000002"]).toBe(100)
    expect(rows[1]["000001"]).toBe(100)
    expect(rows[1]["000002"]).toBe(99)
    expect(rows[2]["000001"]).toBe(101)
    expect(rows[2]["000002"]).toBe(102)
  })
})