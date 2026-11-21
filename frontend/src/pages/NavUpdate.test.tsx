import { beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen } from "@testing-library/react"
import { LanguageProvider } from "@/i18n/LanguageContext"
import type { FetchResult, NavUpdateStatus, Position } from "@/api/types"
import { localDateStr } from "@/lib/format"
import NavUpdate from "./NavUpdate"

const mocks = vi.hoisted(() => ({
  getPositions: vi.fn(),
  getNavUpdateStatus: vi.fn(),
  updateNav: vi.fn(),
}))

vi.mock("@/api/client", () => ({ api: mocks }))

function position(fundCode: string, latestDate: string | null): Position {
  return {
    fund_code: fundCode,
    fund_name: `基金${fundCode}`,
    fund_type: "混合型",
    sector: "消费",
    channel: "支付宝",
    tracking_index: "",
    risk_level: "中风险",
    held_shares: 100,
    total_cost: 1000,
    avg_cost_nav: 10,
    latest_nav: latestDate ? 1.2 : null,
    latest_date: latestDate,
    market_value: 120,
    unrealized_pnl: 20,
    realized_pnl: 0,
    return_rate: 0.02,
    annualized_return: null,
    weight: 0.5,
    buy_count: 1,
    sell_count: 0,
    dividend_count: 0,
    dividend_total: 0,
    total_pnl: 20,
    is_open: true,
  }
}

function idleStatus(results: FetchResult[] = []): NavUpdateStatus {
  return { running: false, total: results.length, done: results.length, current: "", phase: "", results, error: "" }
}

function result(fundCode: string, ok: boolean, message = ""): FetchResult {
  return { fund_code: fundCode, ok, written: ok ? 1 : 0, message, code: "", latest_date: null, latest_nav: null }
}

function renderPage() {
  return render(
    <LanguageProvider>
      <NavUpdate />
    </LanguageProvider>,
  )
}

const today = localDateStr()
const yesterday = localDateStr(new Date(Date.now() - 86400000))

beforeEach(() => {
  mocks.getPositions.mockReset()
  mocks.getNavUpdateStatus.mockReset().mockResolvedValue(idleStatus())
  mocks.updateNav.mockReset()
})

describe("NavUpdate 状态列渲染（renderStatus 各分支）", () => {
  it("无更新结果：无净值→待更新徽章，净值过时→过时徽章，当日净值→已是最新图标", async () => {
    mocks.getPositions.mockResolvedValue([
      position("000001", null),
      position("000002", yesterday),
      position("000003", today),
    ])
    renderPage()

    expect(await screen.findByText("待更新")).toBeInTheDocument()
    expect(screen.getByText("过时")).toBeInTheDocument()
    expect(screen.getByTitle("已是最新")).toBeInTheDocument()
    expect(screen.queryByTitle("更新成功")).not.toBeInTheDocument()
  })

  it("有更新结果：成功基金显示成功图标，失败基金 title 展示失败原因", async () => {
    mocks.getPositions.mockResolvedValue([
      position("000001", today),
      position("000002", null),
    ])
    mocks.getNavUpdateStatus.mockResolvedValue(idleStatus([
      result("000001", true),
      result("000002", false, "抓取失败"),
    ]))
    renderPage()

    expect(await screen.findByTitle("更新成功")).toBeInTheDocument()
    expect(screen.getByTitle("抓取失败")).toBeInTheDocument()
    // 失败明细同时汇总展示
    expect(screen.getByText("000002: 抓取失败")).toBeInTheDocument()
    // 结果优先于新鲜度徽章
    expect(screen.queryByText("待更新")).not.toBeInTheDocument()
  })
})