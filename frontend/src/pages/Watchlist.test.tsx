import { beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { LanguageProvider } from "@/i18n/LanguageContext"
import { CompareProvider } from "@/contexts/CompareContext"
import type { DeletedWatchlistItem } from "@/api/types"
import Watchlist from "./Watchlist"

const mocks = vi.hoisted(() => ({
  getWatchlist: vi.fn(),
  getPositions: vi.fn(),
  getDeletedWatchlist: vi.fn(),
  restoreWatchlistItem: vi.fn(),
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}))

vi.mock("@/api/client", () => ({ api: mocks }))
vi.mock("sonner", () => ({ toast: mocks.toast }))

const deletedItem: DeletedWatchlistItem = {
  fund_code: "000001",
  revision: 1,
  note: "",
  group_name: "",
  added_at: null,
  deleted_at: "2026-01-01T00:00:00",
  fund_name: "基金000001",
}

function renderPage() {
  return render(
    <MemoryRouter>
      <LanguageProvider>
        <CompareProvider>
          <Watchlist />
        </CompareProvider>
      </LanguageProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  mocks.getWatchlist.mockReset().mockResolvedValue([])
  mocks.getPositions.mockReset().mockResolvedValue([])
  mocks.getDeletedWatchlist.mockReset()
  mocks.restoreWatchlistItem.mockReset()
  mocks.toast.success.mockReset()
  mocks.toast.error.mockReset()
  mocks.toast.warning.mockReset()
})

describe("Watchlist", () => {
  it("加载最近删除失败时提示「加载」文案，而非「恢复失败」", async () => {
    mocks.getDeletedWatchlist.mockRejectedValue(new Error("网络错误"))
    renderPage()

    fireEvent.click(await screen.findByRole("button", { name: /最近删除/ }))

    await waitFor(() => expect(mocks.toast.error).toHaveBeenCalledWith("加载最近删除失败"))
    expect(mocks.toast.error).not.toHaveBeenCalledWith("恢复失败")
  })

  it("恢复操作失败仍提示「恢复失败」（原语义不变）", async () => {
    mocks.getDeletedWatchlist.mockResolvedValue({ items: [deletedItem] })
    mocks.restoreWatchlistItem.mockRejectedValue(new Error("网络错误"))
    renderPage()

    fireEvent.click(await screen.findByRole("button", { name: /最近删除/ }))
    fireEvent.click(await screen.findByRole("button", { name: "恢复" }))

    await waitFor(() => expect(mocks.toast.error).toHaveBeenCalledWith("恢复失败"))
    expect(mocks.toast.error).not.toHaveBeenCalledWith("加载最近删除失败")
  })
})