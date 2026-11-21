import { beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { LanguageProvider } from "@/i18n/LanguageContext"
import { CompareProvider } from "@/contexts/CompareContext"
import type { FundFilterItem } from "@/api/types"
import Screener from "./Screener"

const mocks = vi.hoisted(() => ({
  getKeywordMaps: vi.fn(),
  filterFunds: vi.fn(),
  getSparklines: vi.fn(),
  addToWatchlist: vi.fn(),
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}))

vi.mock("@/api/client", () => ({ api: mocks }))
vi.mock("sonner", () => ({ toast: mocks.toast }))

function item(code: string): FundFilterItem {
  return {
    code,
    name: `基金${code}`,
    type: "股票型",
    sector: "",
    scale: null,
    manager: "",
    inception_date: "",
    returns: null,
    risk: null,
    index_tag: "",
    institution_ratio: null,
    individual_ratio: null,
    internal_ratio: null,
    holder_report_date: "",
  }
}

const filterResponse = {
  ok: true,
  funds: [item("000001"), item("000002"), item("000003")],
  total: 3,
  message: "",
  code: "ok",
}

function writeResult(code: string) {
  return {
    ok: true,
    code: "created",
    message: "",
    replayed: false,
    fund_code: code,
    revision: 1,
    changed: true,
    operation_id: 1,
    audit_id: 1,
  }
}

function renderPage() {
  return render(
    <LanguageProvider>
      <CompareProvider>
        <Screener />
      </CompareProvider>
    </LanguageProvider>,
  )
}

async function searchAndSelect(count: number) {
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "测试基金" } })
  fireEvent.click(screen.getByRole("button", { name: "搜索" }))
  await screen.findByText("000001")
  const boxes = screen.getAllByRole("checkbox")
  for (let i = 0; i < count; i++) fireEvent.click(boxes[i])
}

beforeEach(() => {
  mocks.getKeywordMaps.mockReset().mockResolvedValue({ available_types: [], available_sectors: [] })
  mocks.filterFunds.mockReset().mockResolvedValue(filterResponse)
  mocks.getSparklines.mockReset().mockResolvedValue({ ok: true, sparklines: [] })
  mocks.addToWatchlist.mockReset()
  mocks.toast.success.mockReset()
  mocks.toast.error.mockReset()
  mocks.toast.warning.mockReset()
})

describe("Screener 批量加自选", () => {
  it("全部失败时如实 toast.error，不报成功且保留选中集", async () => {
    mocks.addToWatchlist.mockRejectedValue(new Error("网络错误"))
    renderPage()
    await searchAndSelect(2)

    fireEvent.click(screen.getByRole("button", { name: /加自选/ }))

    await waitFor(() => expect(mocks.toast.error).toHaveBeenCalledWith("加入失败"))
    expect(mocks.toast.success).not.toHaveBeenCalled()
    // 选中集保留，便于重试
    expect(screen.getByRole("button", { name: "加自选 (2)" })).toBeInTheDocument()
  })

  it("部分失败时 warning 提示失败数量，成功清空选中", async () => {
    mocks.addToWatchlist.mockImplementation((code: string) =>
      code === "000001"
        ? Promise.reject(new Error("网络错误"))
        : Promise.resolve(writeResult(code)),
    )
    renderPage()
    await searchAndSelect(3)

    fireEvent.click(screen.getByRole("button", { name: /加自选/ }))

    await waitFor(() => expect(mocks.toast.warning).toHaveBeenCalledWith("加入失败 (1/3)"))
    expect(mocks.toast.success).not.toHaveBeenCalled()
    expect(mocks.toast.error).not.toHaveBeenCalled()
    await waitFor(() => expect(screen.queryByRole("button", { name: /加自选/ })).not.toBeInTheDocument())
  })

  it("重复添加（already_exists）视为已存在，不算失败", async () => {
    mocks.addToWatchlist.mockRejectedValue(
      Object.assign(new Error("该基金已在自选中"), { code: "already_exists", status: 409 }),
    )
    renderPage()
    await searchAndSelect(2)

    fireEvent.click(screen.getByRole("button", { name: /加自选/ }))

    await waitFor(() => expect(mocks.toast.success).toHaveBeenCalledWith("已加入自选"))
    expect(mocks.toast.error).not.toHaveBeenCalled()
    expect(mocks.toast.warning).not.toHaveBeenCalled()
  })

  it("相互独立的添加请求并行发起（Promise.all），而非串行等待", async () => {
    const resolvers: (() => void)[] = []
    mocks.addToWatchlist.mockImplementation(
      () => new Promise<void>((resolve) => { resolvers.push(() => resolve()) }),
    )
    renderPage()
    await searchAndSelect(3)

    fireEvent.click(screen.getByRole("button", { name: /加自选/ }))

    // 串行实现只会发起第 1 个请求；并行应一次性发起全部 3 个
    await waitFor(() => expect(mocks.addToWatchlist).toHaveBeenCalledTimes(3))
    expect(mocks.toast.success).not.toHaveBeenCalled()

    resolvers.forEach((resolve) => resolve())
    await waitFor(() => expect(mocks.toast.success).toHaveBeenCalledWith("已加入自选"))
  })
})