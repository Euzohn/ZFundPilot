import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen } from "@testing-library/react"
import { LanguageProvider } from "@/i18n/LanguageContext"
import PnLCalendar from "./PnLCalendar"

function renderCalendar(data: { date: string; pnl: number }[]) {
  return render(
    <LanguageProvider>
      <PnLCalendar data={data} />
    </LanguageProvider>,
  )
}

beforeEach(() => {
  // 仅伪造 Date，固定“当前月”为 2026-11，避免测试依赖真实时钟
  vi.useFakeTimers({ toFake: ["Date"] })
  vi.setSystemTime(new Date("2026-11-21T12:00:00"))
})

afterEach(() => {
  vi.useRealTimers()
})

describe("PnLCalendar 默认定位", () => {
  it("挂载时 data 为空，数据首次到达后定位到最近有数据的月份", () => {
    const { rerender } = renderCalendar([])
    // 空数据先落在当前月
    expect(screen.getByText("2026年11月")).toBeInTheDocument()

    // curve 请求晚于 channelPnl 返回：data 首次到达应重新定位
    rerender(
      <LanguageProvider>
        <PnLCalendar data={[{ date: "2026-08-30", pnl: 10 }, { date: "2026-08-31", pnl: -5 }]} />
      </LanguageProvider>,
    )
    expect(screen.getByText("2026年8月")).toBeInTheDocument()
    expect(screen.queryByText("2026年11月")).toBeNull()
  })

  it("挂载时已有数据则直接定位到末条日期所在月份", () => {
    renderCalendar([{ date: "2025-12-15", pnl: 3 }])
    expect(screen.getByText("2025年12月")).toBeInTheDocument()
  })

  it("数据首次定位后，后续数据更新不覆盖用户手动翻页", () => {
    const data = [{ date: "2026-08-31", pnl: 10 }]
    const { rerender } = renderCalendar([])
    rerender(
      <LanguageProvider>
        <PnLCalendar data={data} />
      </LanguageProvider>,
    )
    expect(screen.getByText("2026年8月")).toBeInTheDocument()

    // 用户手动翻到 10 月
    fireEvent.click(screen.getByTitle("下一月"))
    fireEvent.click(screen.getByTitle("下一月"))
    expect(screen.getByText("2026年10月")).toBeInTheDocument()

    // 数据刷新（末条日期变化）不应把视图拉回 8/9 月
    rerender(
      <LanguageProvider>
        <PnLCalendar data={[...data, { date: "2026-09-01", pnl: 5 }]} />
      </LanguageProvider>,
    )
    expect(screen.getByText("2026年10月")).toBeInTheDocument()
  })
})
