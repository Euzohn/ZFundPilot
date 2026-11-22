import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { LanguageProvider } from "@/i18n/LanguageContext"
import type { AutoInvestPlan } from "@/api/types"
import Transactions from "./Transactions"

// 回归覆盖（OCR 审计 F-B）：
// - 再投资提交金额必须等于只读框显示的 autoAmount（份额×净值）
// - 切换 dividend/reinvest 时清空残留手续费
// - T+1 净值日期按本地日期运算（西时区不回退当天）
// - 定投立即执行 409 → “今日已执行” warning（依赖 client 错误附带 .status/.body）
// - CSV 导出 / 模板下载失败有 toast 错误提示

const mocks = vi.hoisted(() => ({
  getPendingDividendAlertCount: vi.fn(),
  getPreferences: vi.fn(),
  savePreferences: vi.fn(),
  getPositions: vi.fn(),
  fetchFundMeta: vi.fn(),
  getNavForDate: vi.fn(),
  calcFundFee: vi.fn(),
  addTransaction: vi.fn(),
  updateTransaction: vi.fn(),
  updateDividendAlert: vi.fn(),
  updateAlert: vi.fn(),
  getDividendAlerts: vi.fn(),
  exportCsv: vi.fn(),
  downloadTemplate: vi.fn(),
  getAutoInvestPlans: vi.fn(),
  executeAutoInvestPlan: vi.fn(),
}))

vi.mock("@/api/client", () => ({ api: mocks }))

const toastMocks = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
  info: vi.fn(),
  message: vi.fn(),
  loading: vi.fn(),
  dismiss: vi.fn(),
}))

vi.mock("sonner", () => ({ toast: toastMocks, Toaster: () => null }))

function plan(overrides: Partial<AutoInvestPlan> = {}): AutoInvestPlan {
  return {
    id: 1,
    fund_code: "000001",
    fund_name: "测试基金",
    amount: 100,
    cadence: "week",
    day_of_week: 1,
    day_of_month: null,
    channel: "支付宝",
    note: "定投",
    enabled: true,
    next_run: "2026-11-23",
    last_run: null,
    last_tx_id: null,
    created_at: "2026-01-01T00:00:00+08:00",
    updated_at: "2026-01-01T00:00:00+08:00",
    ...overrides,
  }
}

function renderPage(path = "/transactions") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <LanguageProvider>
        <Transactions />
      </LanguageProvider>
    </MemoryRouter>,
  )
}

// 表单 Label 未绑定 htmlFor：按标签文案定位同一 wrapper 内的 input
function inputNearLabel(label: string): HTMLInputElement {
  const wrapper = screen.getByText(label).closest("div")
  const input = wrapper?.querySelector("input")
  if (!input) throw new Error(`标签「${label}」附近未找到 input`)
  return input as HTMLInputElement
}

function actionSelect(): HTMLSelectElement {
  return screen.getAllByRole("combobox")[0] as HTMLSelectElement
}

// 再投资金额框只读，标签为「金额 + 自动」，按「自动」标记定位
function reinvestAmountInput(): HTMLInputElement {
  const wrapper = screen.getByText("自动").closest("div")
  const input = wrapper?.querySelector("input")
  if (!input) throw new Error("未找到再投资自动金额输入框")
  return input as HTMLInputElement
}

beforeEach(() => {
  vi.clearAllMocks()
  mocks.getPendingDividendAlertCount.mockResolvedValue({ count: 0 })
  mocks.getPreferences.mockResolvedValue({})
  mocks.savePreferences.mockResolvedValue({})
  mocks.getPositions.mockResolvedValue([])
  mocks.fetchFundMeta.mockResolvedValue({ ok: true, fund_name: "测试基金", fund_type: "混合型", sector: "" })
  mocks.getNavForDate.mockResolvedValue([{ nav: 2 }])
  // 手续费自动计算拒绝：测试手动填 fee，避免防抖回调干扰
  mocks.calcFundFee.mockRejectedValue(new Error("skip fee calc"))
  mocks.addTransaction.mockResolvedValue({ id: 1 })
  mocks.updateTransaction.mockResolvedValue({})
  mocks.updateDividendAlert.mockResolvedValue({})
  mocks.updateAlert.mockResolvedValue({})
  mocks.getDividendAlerts.mockResolvedValue([])
  mocks.exportCsv.mockResolvedValue(undefined)
  mocks.downloadTemplate.mockResolvedValue(undefined)
  mocks.getAutoInvestPlans.mockResolvedValue([plan()])
  mocks.executeAutoInvestPlan.mockResolvedValue({ tx_id: 7, warnings: [] })
})

describe("再投资金额 / 分红再投资手续费", () => {
  it("再投资提交金额等于只读框显示的自动金额，残留买入金额不生效", async () => {
    renderPage()
    fireEvent.change(inputNearLabel("基金代码"), { target: { value: "000001" } })
    // 先在买入模式填入金额（切换 action 后残留于 amount state）
    fireEvent.change(inputNearLabel("金额（元）"), { target: { value: "1000" } })
    fireEvent.change(actionSelect(), { target: { value: "reinvest" } })
    fireEvent.change(inputNearLabel("红利份额"), { target: { value: "100" } })

    // 净值自动查询回填 2.0000 → 自动金额 = 100 × 2 = 200.00
    await waitFor(() => expect(inputNearLabel("成交净值").value).toBe("2.0000"))
    expect(reinvestAmountInput().value).toBe("200.00")

    fireEvent.click(screen.getByRole("button", { name: "保存交易" }))
    await waitFor(() => expect(mocks.addTransaction).toHaveBeenCalledTimes(1))
    expect(mocks.addTransaction.mock.calls[0][0]).toEqual(expect.objectContaining({
      action: "reinvest", amount: 200, shares: 100, fee: 0,
    }))
  })

  it("分红检查预填的估算金额不覆盖再投资自动金额", async () => {
    renderPage("/transactions?code=000001&action=reinvest&amount=999.50")
    await screen.findByText("红利份额")
    fireEvent.change(inputNearLabel("红利份额"), { target: { value: "100" } })

    await waitFor(() => expect(inputNearLabel("成交净值").value).toBe("2.0000"))
    expect(reinvestAmountInput().value).toBe("200.00")

    fireEvent.click(screen.getByRole("button", { name: "保存交易" }))
    await waitFor(() => expect(mocks.addTransaction).toHaveBeenCalledTimes(1))
    expect(mocks.addTransaction.mock.calls[0][0]).toEqual(expect.objectContaining({
      action: "reinvest", amount: 200, shares: 100,
    }))
  })

  it("买入残留手续费切换到分红后提交为 0", async () => {
    renderPage()
    fireEvent.change(inputNearLabel("基金代码"), { target: { value: "000001" } })
    fireEvent.change(inputNearLabel("金额（元）"), { target: { value: "1000" } })
    fireEvent.change(inputNearLabel("手续费（元）"), { target: { value: "5" } })
    fireEvent.change(actionSelect(), { target: { value: "dividend" } })
    fireEvent.change(inputNearLabel("分红金额（元）"), { target: { value: "50" } })

    fireEvent.click(screen.getByRole("button", { name: "保存交易" }))
    await waitFor(() => expect(mocks.addTransaction).toHaveBeenCalledTimes(1))
    expect(mocks.addTransaction.mock.calls[0][0]).toEqual(expect.objectContaining({
      action: "dividend", amount: 50, fee: 0, nav: null,
    }))
  })

  it("买入残留手续费切换到再投资后提交为 0", async () => {
    renderPage()
    fireEvent.change(inputNearLabel("基金代码"), { target: { value: "000001" } })
    fireEvent.change(inputNearLabel("金额（元）"), { target: { value: "1000" } })
    fireEvent.change(inputNearLabel("手续费（元）"), { target: { value: "5" } })
    fireEvent.change(actionSelect(), { target: { value: "reinvest" } })
    fireEvent.change(inputNearLabel("红利份额"), { target: { value: "100" } })

    await waitFor(() => expect(inputNearLabel("成交净值").value).toBe("2.0000"))
    fireEvent.click(screen.getByRole("button", { name: "保存交易" }))
    await waitFor(() => expect(mocks.addTransaction).toHaveBeenCalledTimes(1))
    expect(mocks.addTransaction.mock.calls[0][0]).toEqual(expect.objectContaining({
      action: "reinvest", amount: 200, fee: 0,
    }))
  })
})

describe("T+1 净值日期（本地日期运算）", () => {
  const originalTZ = process.env.TZ
  beforeEach(() => { process.env.TZ = "America/New_York" })
  afterEach(() => {
    if (originalTZ === undefined) delete process.env.TZ
    else process.env.TZ = originalTZ
  })

  it("西时区下勾选 15 点后查询次日净值，而非回退当天", async () => {
    renderPage()
    fireEvent.change(inputNearLabel("基金代码"), { target: { value: "000001" } })
    fireEvent.change(inputNearLabel("交易日期"), { target: { value: "2026-11-21" } })
    fireEvent.click(screen.getByLabelText("15:00 后"))

    // 旧实现 new Date("2026-11-21") 按 UTC 午夜解析，UTC-5 下 +1 天仍回到 11-21
    await waitFor(() => expect(mocks.getNavForDate).toHaveBeenLastCalledWith("000001", "2026-11-22"))
  })

  it("月末勾选 15 点后跨月/跨年正确", async () => {
    renderPage()
    fireEvent.change(inputNearLabel("基金代码"), { target: { value: "000001" } })
    fireEvent.change(inputNearLabel("交易日期"), { target: { value: "2026-12-31" } })
    fireEvent.click(screen.getByLabelText("15:00 后"))

    await waitFor(() => expect(mocks.getNavForDate).toHaveBeenLastCalledWith("000001", "2027-01-01"))
  })
})

describe("定投立即执行 409 分支", () => {
  it("当日已执行（409）显示友好 warning 而非通用错误", async () => {
    renderPage("/transactions?tab=auto-invest")
    const btn = await screen.findByRole("button", { name: "立即执行" })
    // 与 client.ts apiErrorFromResponse 抛出的错误形状一致（.status/.body）
    mocks.executeAutoInvestPlan.mockRejectedValue(
      Object.assign(new Error("该定投计划今日已执行"), { status: 409, body: { detail: "该定投计划今日已执行" } }),
    )
    fireEvent.click(btn)

    await waitFor(() => expect(toastMocks.warning).toHaveBeenCalledWith("该定投计划今日已执行"))
    expect(toastMocks.error).not.toHaveBeenCalled()
    expect(mocks.executeAutoInvestPlan).toHaveBeenCalledWith(1)
  })

  it("非 409 错误仍走通用错误 toast", async () => {
    renderPage("/transactions?tab=auto-invest")
    const btn = await screen.findByRole("button", { name: "立即执行" })
    mocks.executeAutoInvestPlan.mockRejectedValue(
      Object.assign(new Error("服务器错误"), { status: 500, body: { detail: "服务器错误" } }),
    )
    fireEvent.click(btn)

    await waitFor(() => expect(toastMocks.error).toHaveBeenCalled())
    expect(toastMocks.warning).not.toHaveBeenCalled()
  })
})

describe("定投立即执行成功提示（P3 手动执行透明化）", () => {
  it("成功 toast 附带下次定时说明：手动执行不影响定投计划", async () => {
    renderPage("/transactions?tab=auto-invest")
    const btn = await screen.findByRole("button", { name: "立即执行" })
    fireEvent.click(btn)

    await waitFor(() => expect(toastMocks.success).toHaveBeenCalledWith(
      "定投执行成功，交易 ID: 7 下次定时：2026-11-23（不受本次执行影响）",
    ))
  })
})

describe("CSV 导出 / 模板下载错误处理", () => {
  it("导出失败时 toast 错误提示", async () => {
    renderPage("/transactions?tab=csv")
    mocks.exportCsv.mockRejectedValue(new Error("导出失败"))
    fireEvent.click(screen.getByRole("button", { name: "导出为 CSV" }))
    await waitFor(() => expect(toastMocks.error).toHaveBeenCalled())
  })

  it("导出成功时 toast 成功提示", async () => {
    renderPage("/transactions?tab=csv")
    fireEvent.click(screen.getByRole("button", { name: "导出为 CSV" }))
    await waitFor(() => expect(toastMocks.success).toHaveBeenCalledWith("已导出 CSV"))
  })

  it("模板下载失败时 toast 错误提示", async () => {
    renderPage("/transactions?tab=csv")
    mocks.downloadTemplate.mockRejectedValue(new Error("下载失败"))
    fireEvent.click(screen.getByRole("button", { name: "下载 CSV 模板" }))
    await waitFor(() => expect(toastMocks.error).toHaveBeenCalled())
  })
})