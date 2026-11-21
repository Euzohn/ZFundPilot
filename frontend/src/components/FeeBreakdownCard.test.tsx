import { describe, expect, it } from "vitest"
import { fireEvent, render, screen } from "@testing-library/react"
import { LanguageProvider } from "@/i18n/LanguageContext"
import type { CalcFeeResponse } from "@/api/types"
import FeeBreakdownCard from "./FeeBreakdownCard"

const result: CalcFeeResponse = {
  fee: 3,
  rate: 0.005,
  label: "赎回费",
  code: "redemption_fee",
  amount: 1000,
  nav: 1.2,
  lots: [
    { buy_date: "2024-01-05", buy_shares: 1000, used_shares: 500, days_held: 300, rate: 0.005, fee: 1.5 },
    { buy_date: "2023-12-31", buy_shares: 800, used_shares: 300, days_held: 400, rate: 0.0025, fee: 1.5 },
  ],
}

describe("FeeBreakdownCard FIFO 买入日期展示", () => {
  it("买入日期的所有连字符都替换为斜杠（24/01/05 而非 24/01-05）", () => {
    const { container } = render(
      <LanguageProvider>
        <FeeBreakdownCard result={result} action="sell" />
      </LanguageProvider>,
    )
    fireEvent.click(screen.getByRole("button", { name: /查看明细/ }))

    expect(container.textContent).toContain("24/01/05")
    expect(container.textContent).toContain("23/12/31")
    expect(container.textContent).not.toContain("24/01-05")
    expect(container.textContent).not.toContain("23/12-31")
  })
})
