import { beforeEach, describe, expect, it, vi } from "vitest"
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { LanguageProvider } from "@/i18n/LanguageContext"
import { ChatProvider, type ExtractedTx } from "@/contexts/ChatContext"
import type { CalcFeeResponse } from "@/api/types"
import AIChat, { TxConfirmCard } from "./AIChat"

const mocks = vi.hoisted(() => ({
  getAIConfig: vi.fn(),
  getSystemPrompt: vi.fn(),
  getAIUsage: vi.fn(),
  calcFundFee: vi.fn(),
  streamChat: vi.fn(),
  addTransaction: vi.fn(),
}))

vi.mock("@/api/client", () => ({ api: mocks }))

function feeRes(overrides: Partial<CalcFeeResponse> = {}): CalcFeeResponse {
  return {
    fee: 1.5, rate: 0.0015, label: "申购费", code: "purchase_fee",
    amount: 1000, nav: null, lots: null,
    ...overrides,
  }
}

function txContent(tx: Record<string, unknown>): string {
  return "```json\n" + JSON.stringify({ tool: "add_transaction", ...tx }) + "\n```"
}

// 两个会话在相同消息下标处各有一笔待确认交易（复现卡片实例复用场景）
function seedTwoChats() {
  localStorage.setItem("zfundpilot_chat_sessions", JSON.stringify({
    activeId: "chat-a",
    activeTitle: "会话A",
    activeMessages: [
      { role: "user", content: "买入000001" },
      { role: "assistant", content: txContent({ fund_code: "000001", action: "buy", date: "2026-01-05", amount: 1000, fee: 0 }) },
    ],
    activeTxStatus: {},
    activeSystemPrompt: "sys",
    includeContext: true,
    archive: [{
      id: "chat-b",
      title: "会话B",
      messages: [
        { role: "user", content: "买入000002" },
        { role: "assistant", content: txContent({ fund_code: "000002", action: "buy", date: "2026-02-10", amount: 2000, fee: 0 }) },
      ],
      txStatus: {},
      systemPrompt: "sys",
      updatedAt: "2026-02-10T10:00:00.000Z",
    }],
  }))
}

function renderPage() {
  return render(
    <LanguageProvider>
      <ChatProvider>
        <AIChat />
      </ChatProvider>
    </LanguageProvider>,
  )
}

function sellTx(code: string, shares: number, date: string): ExtractedTx {
  return {
    fund_code: code, action: "sell", date, after_three: false,
    amount: null, shares, nav: null, fee: 0, channel: "", note: "",
  }
}

function renderCard(tx: ExtractedTx, onConfirm = vi.fn()) {
  const utils = render(
    <LanguageProvider>
      <TxConfirmCard tx={tx} adding={false} onConfirm={onConfirm} onDiscard={() => {}} />
    </LanguageProvider>,
  )
  return { ...utils, onConfirm }
}

beforeEach(() => {
  mocks.getAIConfig.mockReset().mockResolvedValue({ base_url: "http://x", model: "m", has_key: true, web_search: false, custom_prompt: "" })
  mocks.getSystemPrompt.mockReset().mockResolvedValue({ system_prompt: "sys" })
  mocks.getAIUsage.mockReset().mockResolvedValue({ today: 0, total: 0, recent: [] })
  mocks.calcFundFee.mockReset().mockResolvedValue(feeRes())
  mocks.streamChat.mockReset().mockImplementation(() => new Promise<void>(() => {}))
  mocks.addTransaction.mockReset().mockResolvedValue({ id: 1 })
})

describe("AIChat 会话切换状态隔离", () => {
  it("切换会话后卡片重挂载，手续费编辑值不串会话", async () => {
    mocks.calcFundFee.mockImplementation((code: string) =>
      Promise.resolve(code === "000001" ? feeRes({ fee: 1.5, amount: 1000 }) : feeRes({ fee: 2.5, amount: 2000 })))
    seedTwoChats()
    renderPage()

    const feeInput = await screen.findByRole("spinbutton")
    await waitFor(() => expect(feeInput).toHaveValue(1.5))
    fireEvent.change(feeInput, { target: { value: "9.99" } })
    expect(feeInput).toHaveValue(9.99)

    // 打开历史会话下拉并切换到会话B（相同下标处也有待确认交易）
    fireEvent.click(screen.getByRole("button", { name: /会话A/ }))
    fireEvent.click(await screen.findByText("会话B"))

    await waitFor(() => expect(screen.getByRole("spinbutton")).toHaveValue(2.5))
    expect(screen.getByText("000002")).toBeInTheDocument()
    expect(screen.queryByText("000001")).not.toBeInTheDocument()
  })

  it("streaming 期间历史会话入口禁用，点击不切换会话", async () => {
    let finishStream: (() => void) | null = null
    mocks.streamChat.mockImplementation(() => new Promise<void>((resolve) => { finishStream = resolve }))
    seedTwoChats()
    renderPage()
    await screen.findByRole("spinbutton")

    // 先打开历史下拉，再开始流式回复
    fireEvent.click(screen.getByRole("button", { name: /会话A/ }))
    await screen.findByText("会话B")
    const textarea = screen.getByPlaceholderText(/输入消息/)
    fireEvent.change(textarea, { target: { value: "你好" } })
    fireEvent.keyDown(textarea, { key: "Enter" })

    await waitFor(() => expect(screen.getByRole("button", { name: /会话A/ })).toBeDisabled())
    expect(screen.getByRole("button", { name: /新对话/ })).toBeDisabled()
    const row = screen.getByText("会话B").closest("[aria-disabled]")
    expect(row).toHaveAttribute("aria-disabled", "true")

    fireEvent.click(screen.getByText("会话B"))
    expect(screen.getByRole("button", { name: /会话A/ })).toBeInTheDocument()
    expect(screen.queryByText("000002")).not.toBeInTheDocument()

    await act(async () => { finishStream!() })
    await waitFor(() => expect(screen.getByRole("button", { name: /会话A/ })).toBeEnabled())
  })
})

describe("TxConfirmCard 费用估算", () => {
  it("卖出缺日期时补填 editDate 触发估算，确认携带估算金额/净值", async () => {
    mocks.calcFundFee.mockResolvedValue(feeRes({ fee: 2.5, amount: 750, nav: 1.5 }))
    const { container, onConfirm } = renderCard(sellTx("000001", 500, ""))
    expect(mocks.calcFundFee).not.toHaveBeenCalled()

    const dateInput = container.querySelector('input[type="date"]') as HTMLInputElement
    fireEvent.change(dateInput, { target: { value: "2026-03-01" } })

    await waitFor(() => expect(mocks.calcFundFee).toHaveBeenCalledWith("000001", { action: "sell", shares: 500, date: "2026-03-01" }))
    await waitFor(() => expect(screen.getByRole("spinbutton")).toHaveValue(2.5))
    expect(screen.getByText("(估算)")).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: /确认添加/ }))
    expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({
      date: "2026-03-01", fee: 2.5, amount: 750, nav: 1.5,
    }))
  })

  it("tx 身份变化时重置编辑手续费与估算值", async () => {
    let resolveB: ((r: CalcFeeResponse) => void) | null = null
    mocks.calcFundFee
      .mockResolvedValueOnce(feeRes({ fee: 1.5, amount: 600, nav: 1.2 }))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveB = resolve }))

    const { rerender } = renderCard(sellTx("000001", 500, "2026-01-05"))
    await waitFor(() => expect(screen.getByRole("spinbutton")).toHaveValue(1.5))
    expect(screen.getByText("(估算)")).toBeInTheDocument()
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "9.99" } })

    rerender(
      <LanguageProvider>
        <TxConfirmCard tx={sellTx("000002", 800, "2026-02-10")} adding={false} onConfirm={() => {}} onDiscard={() => {}} />
      </LanguageProvider>,
    )

    // 旧会话的编辑值/估算值立即清空，不带入新交易
    expect((screen.getByRole("spinbutton") as HTMLInputElement).value).toBe("")
    expect(screen.queryByText("(估算)")).not.toBeInTheDocument()

    await act(async () => { resolveB!(feeRes({ fee: 2.5, amount: 1600, nav: 2 })) })
    await waitFor(() => expect(screen.getByRole("spinbutton")).toHaveValue(2.5))
  })

  it("过期 calcFundFee 响应不覆盖新 tx 的估算（stale 守卫）", async () => {
    let resolveA: ((r: CalcFeeResponse) => void) | null = null
    let resolveB: ((r: CalcFeeResponse) => void) | null = null
    mocks.calcFundFee
      .mockImplementationOnce(() => new Promise((resolve) => { resolveA = resolve }))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveB = resolve }))

    const { rerender } = renderCard(sellTx("000001", 500, "2026-01-05"))
    await waitFor(() => expect(mocks.calcFundFee).toHaveBeenCalledTimes(1))

    rerender(
      <LanguageProvider>
        <TxConfirmCard tx={sellTx("000002", 800, "2026-02-10")} adding={false} onConfirm={() => {}} onDiscard={() => {}} />
      </LanguageProvider>,
    )
    await waitFor(() => expect(mocks.calcFundFee).toHaveBeenCalledTimes(2))

    await act(async () => { resolveB!(feeRes({ fee: 2.5, amount: 1600, nav: 2, label: "费率B", code: "label_b" })) })
    await waitFor(() => expect(screen.getByRole("spinbutton")).toHaveValue(2.5))
    expect(screen.getByText(/费率B/)).toBeInTheDocument()

    // 旧请求晚到：不得覆盖新 tx 的手续费/估算/明细
    await act(async () => { resolveA!(feeRes({ fee: 1.5, amount: 600, nav: 1.2, label: "费率A", code: "label_a" })) })
    expect(screen.getByRole("spinbutton")).toHaveValue(2.5)
    expect(screen.getByText(/费率B/)).toBeInTheDocument()
    expect(screen.queryByText(/费率A/)).not.toBeInTheDocument()
  })
})

describe("TxConfirmCard T+1 口径", () => {
  it("盘后卖出按次日日期估算净值/费率，与手工表单 effectiveNavDate 一致", async () => {
    mocks.calcFundFee.mockResolvedValue(feeRes({ fee: 2.5, amount: 750, nav: 1.5 }))
    const tx: ExtractedTx = {
      fund_code: "000001", action: "sell", date: "2026-01-05", after_three: true,
      amount: null, shares: 500, nav: null, fee: 0, channel: "", note: "",
    }
    renderCard(tx)
    await waitFor(() => expect(mocks.calcFundFee).toHaveBeenCalledWith(
      "000001", { action: "sell", shares: 500, date: "2026-01-06" }))
  })

  it("确认提交携带 after_three，供上层换算 is_t1", async () => {
    mocks.calcFundFee.mockResolvedValue(feeRes({ fee: 2.5, amount: 750, nav: 1.5 }))
    const tx: ExtractedTx = {
      fund_code: "000001", action: "sell", date: "2026-01-05", after_three: true,
      amount: null, shares: 500, nav: null, fee: 0, channel: "", note: "",
    }
    const { onConfirm } = renderCard(tx)
    await waitFor(() => expect(screen.getByRole("spinbutton")).toHaveValue(2.5))
    fireEvent.click(screen.getByRole("button", { name: /确认添加/ }))
    expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({
      date: "2026-01-05", after_three: true,
    }))
  })
})

describe("TxConfirmCard 手续费手动值保护", () => {
  it("用户手动改过手续费后，盘后切换触发重算不覆盖手动值", async () => {
    mocks.calcFundFee
      .mockResolvedValueOnce(feeRes({ fee: 2.5, amount: 750, nav: 1.5 }))
      .mockResolvedValueOnce(feeRes({ fee: 3.5, amount: 700, nav: 1.4 }))
    renderCard(sellTx("000001", 500, "2026-01-05"))
    await waitFor(() => expect(screen.getByRole("spinbutton")).toHaveValue(2.5))
    fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "9.99" } })

    // 切换盘后 → navCalcDate 变化触发重算（第二次返回 3.5），手动值不被覆盖
    fireEvent.click(screen.getByRole("button", { name: /15:00 前下单/ }))
    await waitFor(() => expect(mocks.calcFundFee).toHaveBeenCalledTimes(2))
    expect(screen.getByRole("spinbutton")).toHaveValue(9.99)
  })

  it("未手动改过时重算正常更新自动估算值", async () => {
    mocks.calcFundFee
      .mockResolvedValueOnce(feeRes({ fee: 2.5, amount: 750, nav: 1.5 }))
      .mockResolvedValueOnce(feeRes({ fee: 3.5, amount: 700, nav: 1.4 }))
    renderCard(sellTx("000001", 500, "2026-01-05"))
    await waitFor(() => expect(screen.getByRole("spinbutton")).toHaveValue(2.5))
    fireEvent.click(screen.getByRole("button", { name: /15:00 前下单/ }))
    await waitFor(() => expect(screen.getByRole("spinbutton")).toHaveValue(3.5))
  })
})

describe("AIChat 确认并发守卫与归档行键盘可达", () => {
  it("快速双击确认只提交一次（addingRef 同步拦截）", async () => {
    let resolveAdd!: (v: { id: number }) => void
    mocks.addTransaction.mockImplementation(() => new Promise(res => { resolveAdd = res }))
    seedTwoChats()
    renderPage()
    const btn = await screen.findByRole("button", { name: /确认添加/ })
    fireEvent.click(btn)
    fireEvent.click(btn)
    expect(mocks.addTransaction).toHaveBeenCalledTimes(1)
    await act(async () => { resolveAdd({ id: 1 }) })
  })

  it("归档会话行可聚焦且 Enter 触发切换", async () => {
    seedTwoChats()
    renderPage()
    fireEvent.click(screen.getByRole("button", { name: /会话A/ }))
    const title = await screen.findByText("会话B")
    const row = title.closest('[role="button"]') as HTMLElement
    expect(row).toHaveAttribute("tabindex", "0")
    fireEvent.keyDown(row, { key: "Enter" })
    await waitFor(() => expect(screen.getByText("000002")).toBeInTheDocument())
    expect(screen.queryByText("000001")).not.toBeInTheDocument()
  })
})
