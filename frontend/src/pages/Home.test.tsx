import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { LanguageProvider } from "@/i18n/LanguageContext"
import type { PortfolioSummary } from "@/api/types"
import Home from "./Home"

const mocks = vi.hoisted(() => ({
  getSummary: vi.fn(),
  getAuthStatus: vi.fn(),
  getPreferences: vi.fn(),
}))

vi.mock("@/api/client", () => ({ api: mocks }))

function summary(asOfDate: string): PortfolioSummary {
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
    as_of_date: asOfDate,
    daily_pnl: 10,
    daily_return: 0.01,
    week_pnl: 20,
    week_return: 0.02,
    month_pnl: 30,
    month_return: 0.03,
    year_pnl: 40,
    year_return: 0.04,
  }
}

function renderHome() {
  return render(
    <MemoryRouter>
      <LanguageProvider>
        <Home />
      </LanguageProvider>
    </MemoryRouter>,
  )
}

function reducedMotionMock(matches: boolean) {
  vi.stubGlobal("matchMedia", vi.fn((query: string) => ({
    matches,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })))
}

beforeEach(() => {
  vi.useFakeTimers()
  mocks.getSummary.mockReset().mockResolvedValue(summary("2026-11-20"))
  mocks.getAuthStatus.mockReset().mockResolvedValue({ required: true, version: "1.0.0" })
  mocks.getPreferences.mockReset().mockResolvedValue({})
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe("Home 今天/昨天日期随 now 滚动", () => {
  it("跨天后今日收益标签变为昨日收益，净值最新状态同步失效", async () => {
    reducedMotionMock(false)
    vi.setSystemTime(new Date("2026-11-20T23:59:30"))
    renderHome()
    await act(async () => { await vi.advanceTimersByTimeAsync(100) })

    // 挂载当日：as_of_date=今天 → 今日收益 + 净值「最新」
    expect(screen.getByText("今日收益")).toBeInTheDocument()
    expect(screen.getByText("最新")).toBeInTheDocument()

    // 跨过午夜，分钟 tick 更新 now → 日期字符串重新派生
    vi.setSystemTime(new Date("2026-11-21T00:00:01"))
    await act(async () => { await vi.advanceTimersByTimeAsync(1100) })

    expect(screen.getByText("昨日收益")).toBeInTheDocument()
    expect(screen.queryByText("今日收益")).not.toBeInTheDocument()
    expect(screen.queryByText("最新")).not.toBeInTheDocument()
    expect(screen.getByText("2026-11-20")).toBeInTheDocument()
  })

  it("减少动效模式下 now 仍按分钟更新，跨天标签同样正确滚动", async () => {
    reducedMotionMock(true)
    vi.setSystemTime(new Date("2026-11-20T23:59:30"))
    renderHome()
    await act(async () => { await vi.advanceTimersByTimeAsync(100) })

    expect(screen.getByText("今日收益")).toBeInTheDocument()

    vi.setSystemTime(new Date("2026-11-21T00:00:01"))
    await act(async () => { await vi.advanceTimersByTimeAsync(1100) })

    expect(screen.getByText("昨日收益")).toBeInTheDocument()
    expect(screen.queryByText("今日收益")).not.toBeInTheDocument()
  })
})