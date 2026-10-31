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
  getPreferences: vi.fn(),
  savePreferences: vi.fn(),
}))

vi.mock("@/api/client", () => ({ api: mocks }))

beforeEach(() => {
  mocks.getPendingDividendAlertCount.mockReset().mockResolvedValue({ count: 0 })
  mocks.getPendingAlertCount.mockReset().mockResolvedValue({ count: 0 })
  mocks.getProposalCount.mockReset().mockResolvedValue({ pending: 2 })
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
})
