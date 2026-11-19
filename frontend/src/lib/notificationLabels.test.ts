import { beforeEach, describe, expect, it, vi } from "vitest"

const mocks = vi.hoisted(() => ({ lang: "zh" as "zh" | "en" }))
vi.mock("@/i18n/LanguageContext", () => ({
  getCurrentLang: () => mocks.lang,
}))

import {
  NOTIFICATION_TITLES,
  invalidSourceLabel,
  notificationTarget,
  notificationTitle,
  sourceLabel,
} from "./notificationLabels"

beforeEach(() => {
  mocks.lang = "zh"
})

const SAMPLE_PARAMS: Record<string, Record<string, unknown>> = {
  dividend_detected: {
    fund_code: "005827", fund_name: "蓝筹精选", ex_date: "2026-11-11",
    channel: "支付宝", per_share: 0.05, estimated_amount: 50,
  },
  tp_sl_triggered: {
    fund_code: "005827", fund_name: "蓝筹精选", alert_type: "take_profit",
    triggered_return: 0.25, threshold: 0.2,
  },
  auto_invest_skipped: {
    plan_id: 1, fund_code: "005827", skip_code: "suspended", date: "2026-11-19",
  },
  auto_invest_error: { plan_id: 1, fund_code: "005827", error: "boom" },
  auto_invest_task_error: { date: "2026-11-19", error: "boom" },
  job_failed: { job_id: 11, job_type: "data_refresh", error: "timeout" },
  job_interrupted: { job_id: 12 },
  nav_update_failed: { date: "2026-11-19", count: 3, funds: [] },
  data_health_abnormal: {
    date: "2026-11-19", stale_nav_fund_count: 2,
    missing_nav_fund_count: 0, pending_t1_transaction_count: 1,
  },
}

describe("notification titles", () => {
  it("covers all backend title codes", () => {
    for (const code of Object.keys(SAMPLE_PARAMS)) {
      expect(NOTIFICATION_TITLES[code]).toBeDefined()
      expect(notificationTitle(code, SAMPLE_PARAMS[code])).toBeTruthy()
    }
  })

  it("english output has no Chinese characters (data params aside)", () => {
    mocks.lang = "en"
    const enParams: Record<string, Record<string, unknown>> = {
      ...SAMPLE_PARAMS,
      dividend_detected: { ...SAMPLE_PARAMS.dividend_detected, fund_name: "Blue Chip", channel: "Alipay" },
      tp_sl_triggered: { ...SAMPLE_PARAMS.tp_sl_triggered, fund_name: "Blue Chip" },
    }
    for (const code of Object.keys(enParams)) {
      expect(notificationTitle(code, enParams[code])).not.toMatch(/[\u4e00-\u9fff]/)
    }
  })

  it("falls back to raw code when unknown", () => {
    expect(notificationTitle("unknown_code", {})).toBe("unknown_code")
  })

  it("dividend title interpolates name/ex-date/channel", () => {
    const zh = notificationTitle("dividend_detected", SAMPLE_PARAMS.dividend_detected)
    expect(zh).toContain("蓝筹精选")
    expect(zh).toContain("2026-11-11")
    expect(zh).toContain("支付宝")
    mocks.lang = "en"
    const en = notificationTitle("dividend_detected", {
      fund_name: "Blue Chip", ex_date: "2026-11-11", channel: "",
    })
    expect(en).toContain("Blue Chip")
    expect(en).not.toContain("·")
  })

  it("tp_sl distinguishes take_profit / stop_loss", () => {
    const tp = notificationTitle("tp_sl_triggered", SAMPLE_PARAMS.tp_sl_triggered)
    const sl = notificationTitle("tp_sl_triggered", {
      ...SAMPLE_PARAMS.tp_sl_triggered, alert_type: "stop_loss",
    })
    expect(tp).toContain("止盈")
    expect(sl).toContain("止损")
    expect(tp).toContain("25.0%")
  })

  it("auto_invest_skipped maps all three skip codes", () => {
    expect(notificationTitle("auto_invest_skipped", { skip_code: "suspended", fund_code: "001" }))
      .toContain("暂停申购")
    expect(notificationTitle("auto_invest_skipped", { skip_code: "limit_exceeded", fund_code: "001" }))
      .toContain("超出限购额度")
    expect(notificationTitle("auto_invest_skipped", { skip_code: "below_minimum", fund_code: "001" }))
      .toContain("低于申购起点")
    mocks.lang = "en"
    expect(notificationTitle("auto_invest_skipped", { skip_code: "suspended", fund_code: "001" }))
      .toContain("subscription suspended")
  })

  it("unknown skip code falls back to raw value", () => {
    expect(notificationTitle("auto_invest_skipped", { skip_code: "weird", fund_code: "001" }))
      .toContain("weird")
  })

  it("job_failed maps both job types", () => {
    expect(notificationTitle("job_failed", { job_type: "data_refresh" })).toContain("数据刷新任务")
    expect(notificationTitle("job_failed", { job_type: "dca_backtest" })).toContain("定投回测任务")
    mocks.lang = "en"
    expect(notificationTitle("job_failed", { job_type: "dca_backtest" })).toContain("DCA backtest job")
  })

  it("nav_update_failed interpolates count", () => {
    expect(notificationTitle("nav_update_failed", { count: 3 })).toContain("3 只基金")
    mocks.lang = "en"
    expect(notificationTitle("nav_update_failed", { count: 3 })).toContain("3 fund(s)")
  })

  it("data_health only lists non-zero parts with neutral separator", () => {
    const zh = notificationTitle("data_health_abnormal", SAMPLE_PARAMS.data_health_abnormal)
    expect(zh).toContain("2 只净值过期")
    expect(zh).toContain("1 笔待确认")
    expect(zh).not.toContain("缺净值")
    mocks.lang = "en"
    const en = notificationTitle("data_health_abnormal", SAMPLE_PARAMS.data_health_abnormal)
    expect(en).toContain("2 stale NAV")
    expect(en).toContain("1 pending T+1")
    expect(en).not.toContain("missing")
  })
})

describe("source labels and targets", () => {
  it("labels all six source types zh/en", () => {
    const sources = ["dividend", "tpsl", "auto_invest", "job", "nav_update", "data_health"]
    for (const s of sources) {
      expect(sourceLabel(s)).toBeTruthy()
      mocks.lang = "en"
      expect(sourceLabel(s)).not.toMatch(/[\u4e00-\u9fff]/)
      mocks.lang = "zh"
    }
  })

  it("unknown source falls back to raw value", () => {
    expect(sourceLabel("weird")).toBe("weird")
  })

  it("targets map to source pages", () => {
    expect(notificationTarget({ source_type: "dividend" })).toBe("/transactions")
    expect(notificationTarget({ source_type: "tpsl" })).toBe("/returns")
    expect(notificationTarget({ source_type: "auto_invest" })).toBe("/transactions?tab=auto-invest")
    expect(notificationTarget({ source_type: "job" })).toBe("/nav")
    expect(notificationTarget({ source_type: "nav_update" })).toBe("/nav")
    expect(notificationTarget({ source_type: "data_health" })).toBe("/overview")
  })

  it("invalid source label bilingual", () => {
    expect(invalidSourceLabel()).toBe("已失效")
    mocks.lang = "en"
    expect(invalidSourceLabel()).toBe("Expired")
  })
})