import { beforeEach, describe, expect, it, vi } from "vitest"
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

vi.mock("@/api/client", () => ({ api: mocks }))
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }))

const alert: DividendAlert = {
  id: 7,
  fund_code: "000001",
  fund_name: "测试基金",
  status: "pending",
  created_at: "2026-11-01T00:00:00",
  ex_date: "2026-11-10",
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
