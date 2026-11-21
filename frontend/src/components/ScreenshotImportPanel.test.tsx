import { beforeEach, describe, expect, it, vi } from "vitest"
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { LanguageProvider } from "@/i18n/LanguageContext"
import type { ParsedTxItem, ParseScreenshotResult } from "@/api/types"
import ScreenshotImportPanel from "./ScreenshotImportPanel"

const mocks = vi.hoisted(() => ({
  parseScreenshot: vi.fn(),
  confirmImport: vi.fn(),
  reconcileHoldings: vi.fn(),
}))

vi.mock("@/api/client", () => ({ api: mocks }))
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }))

function txItem(overrides: Partial<ParsedTxItem> = {}): ParsedTxItem {
  return {
    fund_name: "测试基金",
    fund_code: "000001",
    action: "buy",
    date: "2026-11-01",
    amount: 1000,
    shares: null,
    nav: null,
    fee: null,
    channel: "",
    note: "",
    is_t1: false,
    code_status: "exact",
    candidates: [],
    ...overrides,
  }
}

function renderPanel() {
  return render(
    <LanguageProvider>
      <ScreenshotImportPanel />
    </LanguageProvider>,
  )
}

function selectImage(container: HTMLElement, name = "shot.png") {
  const input = container.querySelector('input[type="file"]') as HTMLInputElement
  const file = new File(["fake-image"], name, { type: "image/png" })
  fireEvent.change(input, { target: { files: [file] } })
}

beforeEach(() => {
  mocks.parseScreenshot.mockReset()
  mocks.confirmImport.mockReset().mockResolvedValue({ imported: 2 })
  mocks.reconcileHoldings.mockReset()
  // jsdom 未实现 object URL
  URL.createObjectURL = vi.fn(() => "blob:mock-preview")
  URL.revokeObjectURL = vi.fn()
})

describe("ScreenshotImportPanel 导入完整性校验", () => {
  it("残缺行不计入有效数、不被导入，并显示按操作类型的提示", async () => {
    const items = [
      txItem(),                                                        // 有效买入
      txItem({ action: "sell", amount: null, shares: 100 }),           // 有效卖出
      txItem({ amount: null }),                                        // 买入缺金额
      txItem({ action: "sell", amount: 500, shares: null }),           // 卖出缺份额
      txItem({ action: "reinvest", amount: 200, shares: null }),       // 再投资缺份额
      txItem({ action: "dividend", amount: null, shares: 100 }),       // 分红缺金额
      txItem({ is_duplicate: true }),                                  // 重复行（原有行为）
    ]
    mocks.parseScreenshot.mockResolvedValue({ ok: true, items, error: "" })

    const { container } = renderPanel()
    selectImage(container)
    fireEvent.click(screen.getByRole("button", { name: "开始解析" }))

    await screen.findByText(/识别到 7 笔交易/)
    // 有效数只含 2 笔完整行
    expect(screen.getByText("2/7 笔有效")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "确认导入 2 笔" })).toBeInTheDocument()
    // 残缺行可见提示
    expect(screen.getByText("请填写买入金额")).toBeInTheDocument()
    expect(screen.getByText("请填写卖出份额")).toBeInTheDocument()
    expect(screen.getByText("请填写红利份额")).toBeInTheDocument()
    expect(screen.getByText("请填写分红金额")).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: "确认导入 2 笔" }))
    await waitFor(() => expect(mocks.confirmImport).toHaveBeenCalledTimes(1))
    const txs = mocks.confirmImport.mock.calls[0][0] as { action: string }[]
    expect(txs).toHaveLength(2)
    expect(txs.map(x => x.action).sort()).toEqual(["buy", "sell"])
  })

  it("买入仅有份额无金额时仍视为不完整（与手工新增表单一致）", async () => {
    const items = [txItem({ amount: null, shares: 100, nav: 1.2 })]
    mocks.parseScreenshot.mockResolvedValue({ ok: true, items, error: "" })

    const { container } = renderPanel()
    selectImage(container)
    fireEvent.click(screen.getByRole("button", { name: "开始解析" }))

    await screen.findByText(/识别到 1 笔交易/)
    expect(screen.getByText("0/1 笔有效")).toBeInTheDocument()
    expect(screen.getByText("请填写买入金额")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "确认导入 0 笔" })).toBeDisabled()
    expect(mocks.confirmImport).not.toHaveBeenCalled()
  })

  it("用户补全残缺行后重新计入有效数并可导入", async () => {
    const items = [txItem({ amount: null })]
    mocks.parseScreenshot.mockResolvedValue({ ok: true, items, error: "" })

    const { container } = renderPanel()
    selectImage(container)
    fireEvent.click(screen.getByRole("button", { name: "开始解析" }))
    await screen.findByText(/识别到 1 笔交易/)
    expect(screen.getByText("0/1 笔有效")).toBeInTheDocument()

    // 在预览表格里补填金额
    const amountInput = container.querySelector('td input[type="number"]') as HTMLInputElement
    fireEvent.change(amountInput, { target: { value: "800" } })
    expect(screen.getByText("1/1 笔有效")).toBeInTheDocument()
    expect(screen.queryByText("请填写买入金额")).toBeNull()
  })
})

describe("ScreenshotImportPanel 解析代际守卫", () => {
  it("解析中途移除图片，旧结果不写入预览", async () => {
    let resolveParse!: (v: ParseScreenshotResult) => void
    mocks.parseScreenshot.mockImplementation(() => new Promise(res => { resolveParse = res }))

    const { container } = renderPanel()
    selectImage(container)
    fireEvent.click(screen.getByRole("button", { name: "开始解析" }))
    expect(mocks.parseScreenshot).toHaveBeenCalledTimes(1)

    // 解析在途时移除图片
    fireEvent.click(screen.getByTitle("移除"))
    await act(async () => {
      resolveParse({ ok: true, items: [txItem({ fund_name: "旧图基金" })], error: "" })
    })

    expect(screen.queryByText(/识别到/)).toBeNull()
    expect(screen.queryByText("旧图基金")).toBeNull()
  })

  it("解析中途换图：旧图结果被丢弃，仅展示新图结果", async () => {
    const resolvers: ((v: ParseScreenshotResult) => void)[] = []
    mocks.parseScreenshot.mockImplementation(() => new Promise(res => { resolvers.push(res) }))

    const { container } = renderPanel()
    selectImage(container, "old.png")
    fireEvent.click(screen.getByRole("button", { name: "开始解析" }))

    // 换图后再次解析
    selectImage(container, "new.png")
    fireEvent.click(screen.getByRole("button", { name: "开始解析" }))
    expect(resolvers).toHaveLength(2)

    // 旧请求先返回，新请求后返回
    await act(async () => {
      resolvers[0]({ ok: true, items: [txItem({ fund_name: "旧图基金" })], error: "" })
    })
    await act(async () => {
      resolvers[1]({ ok: true, items: [txItem({ fund_name: "新图基金" })], error: "" })
    })

    expect(screen.queryByText("旧图基金")).toBeNull()
    expect(screen.getByText("新图基金")).toBeInTheDocument()
  })

  it("解析中途切换模式，旧结果不写入任何列表", async () => {
    let resolveParse!: (v: ParseScreenshotResult) => void
    mocks.parseScreenshot.mockImplementation(() => new Promise(res => { resolveParse = res }))

    const { container } = renderPanel()
    selectImage(container)
    fireEvent.click(screen.getByRole("button", { name: "开始解析" }))

    fireEvent.click(screen.getByRole("button", { name: "持仓对账" }))
    await act(async () => {
      resolveParse({ ok: true, items: [txItem()], error: "" })
    })

    expect(screen.queryByText(/识别到/)).toBeNull()
    // 切回交易流水模式也不应出现陈旧数据
    fireEvent.click(screen.getByRole("button", { name: "交易流水" }))
    expect(screen.queryByText(/识别到/)).toBeNull()
  })

  it("解析中途移除图片后重新选图，仍可正常发起新解析", async () => {
    const resolvers: ((v: ParseScreenshotResult) => void)[] = []
    mocks.parseScreenshot.mockImplementation(() => new Promise(res => { resolvers.push(res) }))

    const { container } = renderPanel()
    selectImage(container)
    fireEvent.click(screen.getByRole("button", { name: "开始解析" }))
    fireEvent.click(screen.getByTitle("移除"))

    // 重新选图后解析按钮不应卡在禁用态
    selectImage(container, "again.png")
    const parseBtn = screen.getByRole("button", { name: "开始解析" })
    expect(parseBtn).not.toBeDisabled()
    fireEvent.click(parseBtn)

    await act(async () => {
      resolvers[0]({ ok: true, items: [txItem({ fund_name: "过期结果" })], error: "" })
      resolvers[1]({ ok: true, items: [txItem({ fund_name: "最新结果" })], error: "" })
    })
    expect(screen.queryByText("过期结果")).toBeNull()
    expect(screen.getByText("最新结果")).toBeInTheDocument()
  })
})
