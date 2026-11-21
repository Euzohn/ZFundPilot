import { beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import { LanguageProvider } from "@/i18n/LanguageContext"
import type { OperationProposal, ProposalListResponse, ProposalSummary } from "@/api/types"
import Proposals from "./Proposals"

const mocks = vi.hoisted(() => ({
  getProposals: vi.fn(),
  getProposal: vi.fn(),
  approveProposal: vi.fn(),
  rejectProposal: vi.fn(),
}))

vi.mock("@/api/client", () => ({ api: mocks }))

function summary(overrides: Partial<ProposalSummary> = {}): ProposalSummary {
  return {
    operation_type: "add_transaction",
    operation_label: "新增交易",
    title: "买入 测试基金",
    fund_code: "005827",
    fund_name: "测试基金",
    action: "buy",
    action_label: "买入",
    date: "2026-01-02",
    amount: 1000,
    shares: null,
    nav: null,
    fee: 1,
    channel: "支付宝",
    is_t1: false,
    note: "",
    warnings: [],
    ...overrides,
  }
}

function proposal(id: number, overrides: Partial<ProposalSummary>): OperationProposal {
  return {
    proposal_id: id,
    operation_type: overrides.operation_type ?? "add_transaction",
    operation_label: "新增交易",
    status: "pending",
    risk_level: "medium",
    created_at: "2026-01-01T10:00:00+08:00",
    expires_at: "2026-01-08T10:00:00+08:00",
    reviewed_by: null,
    reviewed_at: null,
    rejection_reason: "",
    execution_result: null,
    audit_id: null,
    completed_at: null,
    summary: summary(overrides),
    params: {},
    can_cancel: true,
    can_approve: true,
  }
}

function listResponse(items: OperationProposal[]): ProposalListResponse {
  return {
    ok: true,
    code: "ok",
    message: "",
    count: items.length,
    total: items.length,
    pending_count: items.length,
    items,
    pagination: { limit: 100, offset: 0, total: items.length },
  }
}

function renderPage() {
  return render(
    <LanguageProvider>
      <Proposals />
    </LanguageProvider>,
  )
}

// 列表行单元格顺序：0 id / 1 操作类型 / 2 基金 / 3 操作 / 4 日期 / 5 金额 / 6 状态 / 7 创建时间 / 8 按钮
function rowByFundCode(code: string): HTMLElement {
  const row = screen.getByText(code).closest("tr")
  if (!row) throw new Error(`未找到基金代码 ${code} 所在行`)
  return row
}

function cells(row: HTMLElement) {
  const tds = row.querySelectorAll("td")
  return {
    action: tds[3].textContent,
    date: tds[4].textContent,
    amount: tds[5].textContent,
  }
}

beforeEach(() => {
  mocks.getProposals.mockReset().mockResolvedValue(listResponse([]))
  mocks.getProposal.mockReset()
  mocks.approveProposal.mockReset()
  mocks.rejectProposal.mockReset()
})

describe("Proposals 列表列渲染（嵌套三元重构回归）", () => {
  it("各 operation_type 的操作/日期/金额列按类型分派渲染", async () => {
    mocks.getProposals.mockResolvedValue(
      listResponse([
        proposal(1, {
          operation_type: "batch_import",
          fund_code: "900001",
          count: 3,
          actions: { buy: 2, sell: 1 },
          date_range: { from: "2026-01-01", to: "2026-01-03" },
          amount_total: 3000,
        }),
        proposal(2, {
          operation_type: "create_plan",
          fund_code: "900002",
          cadence: "week",
          day_of_week: 2,
          next_run: "2026-01-07",
          amount: 500,
        }),
        proposal(3, {
          operation_type: "execute_plan",
          fund_code: "900003",
          cadence: "month",
          day_of_month: 15,
          trade_date: "2026-01-15",
          date: "2026-01-14",
          amount: 600,
        }),
        proposal(4, {
          operation_type: "resolve_alert",
          fund_code: "900004",
          alert_type: "dividend",
          record_date: "2026-01-02",
          ex_date: "2026-01-05",
          estimated_amount: 88,
        }),
        proposal(5, { fund_code: "900005", action: "buy", date: "2026-01-02", amount: 1000 }),
      ]),
    )
    renderPage()

    // 批量导入行：基金列显示条数而非基金代码
    const batchRow = (await screen.findByText("3 条交易")).closest("tr")!
    expect(cells(batchRow)).toEqual({
      action: "买入×2 卖出×1",
      date: "2026-01-01 ~ 2026-01-03",
      amount: "¥3,000.00",
    })

    await waitFor(() => expect(screen.getByText("900002")).toBeInTheDocument())
    expect(cells(rowByFundCode("900002"))).toEqual({
      action: "每周三",
      date: "2026-01-07",
      amount: "¥500.00",
    })
    // 手动执行：trade_date 优先于 date
    expect(cells(rowByFundCode("900003"))).toEqual({
      action: "每月15日",
      date: "2026-01-15",
      amount: "¥600.00",
    })
    // 提醒：record_date 优先于 ex_date，金额取 estimated_amount
    expect(cells(rowByFundCode("900004"))).toEqual({
      action: "分红提醒",
      date: "2026-01-02",
      amount: "¥88.00",
    })
    // 普通交易：actionLabel / date / amount
    expect(cells(rowByFundCode("900005"))).toEqual({
      action: "买入",
      date: "2026-01-02",
      amount: "¥1,000.00",
    })
  })

  it("缺省字段按原回退链渲染（trade_date/next_run/record_date/estimated_amount）", async () => {
    mocks.getProposals.mockResolvedValue(
      listResponse([
        proposal(11, {
          operation_type: "execute_plan",
          fund_code: "900011",
          cadence: "daily",
          date: "2026-03-01",
        }),
        proposal(12, {
          operation_type: "create_plan",
          fund_code: "900012",
          cadence: "daily",
          next_run: null,
        }),
        proposal(13, {
          operation_type: "resolve_alert",
          fund_code: "900013",
          alert_type: "dividend",
          record_date: null,
          ex_date: "2026-02-01",
          estimated_amount: null,
        }),
        proposal(14, {
          operation_type: "resolve_alert",
          fund_code: "900014",
          alert_type: "take_profit",
          record_date: null,
          ex_date: null,
        }),
      ]),
    )
    renderPage()

    await waitFor(() => expect(screen.getByText("900011")).toBeInTheDocument())
    // execute_plan 无 trade_date → 回退 summary.date
    expect(cells(rowByFundCode("900011"))).toEqual({
      action: "每日",
      date: "2026-03-01",
      amount: "¥1,000.00",
    })
    // 计划 next_run 为 null → "—"
    expect(cells(rowByFundCode("900012")).date).toBe("—")
    // 提醒 record_date 为 null → ex_date；estimated_amount 为 null → "—"（不取 amount）
    expect(cells(rowByFundCode("900013"))).toEqual({
      action: "分红提醒",
      date: "2026-02-01",
      amount: "—",
    })
    // 提醒两个日期都为 null → "—"
    expect(cells(rowByFundCode("900014")).date).toBe("—")
  })
})