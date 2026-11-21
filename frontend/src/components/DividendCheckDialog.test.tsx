import { beforeEach, describe, expect, it, vi } from "vitest"
import { useState } from "react"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { toast } from "sonner"
import { LanguageProvider } from "@/i18n/LanguageContext"
import type { DividendAlert } from "@/api/types"
import DividendCheckDialog from "./DividendCheckDialog"

const mocks = vi.hoisted(() => ({
  getDividendAlerts: vi.fn(),
  deleteDividendAlert: vi.fn(),
  updateDividendAlert: vi.fn(),
  scanDividends: vi.fn(),
}))

const navigateMock = vi.hoisted(() => vi.fn())

vi.mock("@/api/client", () => ({ api: mocks }))
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }))
vi.mock("react-router-dom", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-router-dom")>()),
  useNavigate: () => navigateMock,
}))

const alert: DividendAlert = {
  id: 7,
  fund_code: "000001",
  fund_name: "测试基金",
  status: "pending",
  created_at: "2026-11-01T00:00:00",
  ex_date: "2026-11-10",
  pay_date: "2026-11-13",
  per_share: 0.05,
  held_shares: 1000,
  estimated_amount: 50,
  dividend_method: "cash",
}

function renderDialog() {
  return render(
    <MemoryRouter>
      <LanguageProvider>
        <DividendCheckDialog open={true} onOpenChange={() => {}} />
      </LanguageProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  mocks.getDividendAlerts.mockReset().mockResolvedValue([alert])
  mocks.deleteDividendAlert.mockReset()
  mocks.updateDividendAlert.mockReset()
  mocks.scanDividends.mockReset()
})

describe("DividendCheckDialog 删除提醒", () => {
  it("删除失败时保留列表项并提示错误（与忽略行为一致）", async () => {
    mocks.deleteDividendAlert.mockRejectedValue(new Error("server down"))
    renderDialog()
    await screen.findByText("000001")

    fireEvent.click(screen.getByTitle("删除"))
    fireEvent.click(await screen.findByRole("button", { name: "确认" }))

    await waitFor(() => expect(mocks.deleteDividendAlert).toHaveBeenCalledWith(7))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("删除失败"))
    // 服务端未删除成功，界面必须保留该提醒
    expect(screen.getByText("000001")).toBeInTheDocument()
  })

  it("删除成功后才移除列表项", async () => {
    mocks.deleteDividendAlert.mockResolvedValue(undefined)
    renderDialog()
    await screen.findByText("000001")

    fireEvent.click(screen.getByTitle("删除"))
    fireEvent.click(await screen.findByRole("button", { name: "确认" }))

    await waitFor(() => expect(screen.queryByText("000001")).toBeNull())
    expect(toast.error).not.toHaveBeenCalled()
  })

  it("忽略失败时同样保留列表项", async () => {
    mocks.updateDividendAlert.mockRejectedValue(new Error("server down"))
    renderDialog()
    await screen.findByText("000001")

    fireEvent.click(screen.getByRole("button", { name: "忽略" }))

    await waitFor(() => expect(mocks.updateDividendAlert).toHaveBeenCalledWith(7, "ignored"))
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("忽略失败"))
    expect(screen.getByText("000001")).toBeInTheDocument()
  })
})

// 受控关闭的包装组件，供日期口径测试断言跳转 URL
function ClosableDialog() {
  const [open, setOpen] = useState(true)
  return <DividendCheckDialog open={open} onOpenChange={setOpen} />
}

describe("DividendCheckDialog 记账日期口径", () => {
  beforeEach(() => {
    navigateMock.mockReset()
  })

  it("现金分红确认后跳转预填除息日而非发放日", async () => {
    render(
      <MemoryRouter>
        <LanguageProvider>
          <ClosableDialog />
        </LanguageProvider>
      </MemoryRouter>,
    )
    await screen.findByText("000001")

    fireEvent.click(screen.getByRole("button", { name: /记为分红/ }))

    await waitFor(() => expect(navigateMock).toHaveBeenCalled())
    const url = navigateMock.mock.calls[0][0] as string
    // 后端在流水日冲减投入成本：成本必须与除息日净值下跌同日，否则留下假亏损
    expect(url).toContain("date=2026-11-10")
    expect(url).not.toContain("date=2026-11-13")
  })

  it("再投资同样使用除息日", async () => {
    render(
      <MemoryRouter>
        <LanguageProvider>
          <ClosableDialog />
        </LanguageProvider>
      </MemoryRouter>,
    )
    await screen.findByText("000001")

    // 字符串 name 为规范化全等匹配，不会误点「记为再投」
    fireEvent.click(screen.getByRole("button", { name: "再投资" }))
    fireEvent.click(screen.getByRole("button", { name: /记为再投/ }))

    await waitFor(() => expect(navigateMock).toHaveBeenCalled())
    expect(navigateMock.mock.calls[0][0]).toContain("date=2026-11-10")
  })
})
