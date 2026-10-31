import { beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { LanguageProvider } from "@/i18n/LanguageContext"
import type {
  OperationProposal,
  ProposalActionResult,
  ProposalListResponse,
  ProposalSummary,
} from "@/api/types"
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
    title: "买入 易方达蓝筹精选",
    fund_code: "005827",
    fund_name: "易方达蓝筹精选",
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

function proposal(overrides: Partial<OperationProposal> = {}): OperationProposal {
  return {
    proposal_id: 1,
    operation_type: "add_transaction",
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
    summary: summary(),
    params: { fund_code: "005827" },
    can_cancel: true,
    can_approve: true,
    ...overrides,
  }
}

function listResponse(items: OperationProposal[]): ProposalListResponse {
  return {
    ok: true,
    code: "ok",
    message: "",
    count: items.length,
    total: items.length,
    pending_count: items.filter((item) => item.status === "pending").length,
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

beforeEach(() => {
  mocks.getProposals.mockReset().mockResolvedValue(listResponse([]))
  mocks.getProposal.mockReset()
  mocks.approveProposal.mockReset()
  mocks.rejectProposal.mockReset()
})

describe("Proposals", () => {
  it("切换状态筛选后按新状态重新请求（回归 deps 失效）", async () => {
    mocks.getProposals.mockResolvedValue(listResponse([proposal()]))
    renderPage()

    await waitFor(() => expect(mocks.getProposals).toHaveBeenCalledWith(undefined))

    fireEvent.click(screen.getByRole("button", { name: "待处理" }))

    await waitFor(() => expect(mocks.getProposals).toHaveBeenCalledWith("pending"))
  })

  it("审批失败后刷新列表并关闭确认框", async () => {
    mocks.getProposals.mockResolvedValue(listResponse([proposal()]))
    mocks.approveProposal.mockRejectedValue(new Error("写入失败"))
    renderPage()

    await waitFor(() => expect(mocks.getProposals).toHaveBeenCalledTimes(1))
    fireEvent.click(await screen.findByRole("button", { name: "批准并写入" }))

    const dialog = await screen.findByRole("alertdialog")
    fireEvent.click(within(dialog).getByRole("button", { name: "批准并写入" }))

    await waitFor(() => expect(mocks.approveProposal).toHaveBeenCalledWith(1))
    await waitFor(() => expect(mocks.getProposals).toHaveBeenCalledTimes(2))
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument()
  })

  it("打开详情时重新拉取最新提案而不是复用列表数据", async () => {
    const stale = proposal({
      summary: summary({ fund_name: "列表旧名称", title: "列表旧标题" }),
    })
    const fresh: ProposalActionResult = {
      ...proposal({
        summary: summary({ fund_name: "详情新名称", title: "详情新标题" }),
      }),
      ok: true,
      code: "ok",
      message: "",
    }
    mocks.getProposals.mockResolvedValue(listResponse([stale]))
    mocks.getProposal.mockResolvedValue(fresh)
    renderPage()

    fireEvent.click(await screen.findByRole("button", { name: "详情" }))

    await waitFor(() => expect(mocks.getProposal).toHaveBeenCalledWith(1))
    const dialog = await screen.findByRole("dialog")
    expect(within(dialog).getByText("详情新名称")).toBeInTheDocument()
    expect(within(dialog).getByText("详情新标题")).toBeInTheDocument()
  })
})
