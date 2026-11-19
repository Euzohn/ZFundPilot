import { beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { LanguageProvider } from "@/i18n/LanguageContext"
import { CompareProvider } from "@/contexts/CompareContext"
import Layout from "./Layout"

const mocks = vi.hoisted(() => ({
  getPendingDividendAlertCount: vi.fn(),
  getPendingAlertCount: vi.fn(),
  getProposalCount: vi.fn(),
  getNotificationCount: vi.fn(),
  getPreferences: vi.fn(),
  savePreferences: vi.fn(),
}))

vi.mock("@/api/client", () => ({ api: mocks }))

beforeEach(() => {
  mocks.getPendingDividendAlertCount.mockReset().mockResolvedValue({ count: 0 })
  mocks.getPendingAlertCount.mockReset().mockResolvedValue({ count: 0 })
  mocks.getProposalCount.mockReset().mockResolvedValue({ pending: 2 })
  mocks.getNotificationCount.mockReset().mockResolvedValue({ count: 0 })
  mocks.getPreferences.mockReset().mockResolvedValue({})
  mocks.savePreferences.mockReset().mockResolvedValue({ ok: true })
})

describe("Layout", () => {
  it("收到提案变更事件后重新拉取待处理角标", async () => {
    render(
      <MemoryRouter>
        <LanguageProvider>
          <CompareProvider>
            <Layout />
          </CompareProvider>
        </LanguageProvider>
      </MemoryRouter>,
    )

    await waitFor(() => expect(mocks.getProposalCount).toHaveBeenCalledTimes(1))

    fireEvent(window, new Event("zfund:proposals-changed"))

    await waitFor(() => expect(mocks.getProposalCount).toHaveBeenCalledTimes(2))
  })

  it("通知徽章挂载时拉取未读数，通知变更事件后刷新", async () => {
    mocks.getNotificationCount.mockResolvedValue({ count: 3 })
    render(
      <MemoryRouter>
        <LanguageProvider>
          <CompareProvider>
            <Layout />
          </CompareProvider>
        </LanguageProvider>
      </MemoryRouter>,
    )

    // 移动端顶栏 + 桌面侧栏各一个 Bell，两者都挂载
    await waitFor(() => expect(mocks.getNotificationCount).toHaveBeenCalledTimes(2))

    fireEvent(window, new Event("zfund:notifications-changed"))

    await waitFor(() => expect(mocks.getNotificationCount).toHaveBeenCalledTimes(4))
  })
})
