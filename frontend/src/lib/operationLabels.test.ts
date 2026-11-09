import { beforeEach, describe, expect, it, vi } from "vitest"

const mocks = vi.hoisted(() => ({ lang: "zh" as "zh" | "en" }))
vi.mock("@/i18n/LanguageContext", () => ({
  getCurrentLang: () => mocks.lang,
}))

import {
  alertTypeLabel,
  cadenceLabel,
  feeSourceLabel,
  operationLabel,
  planScheduleLabel,
  proposalTitle,
} from "./operationLabels"
import type { ProposalSummary } from "@/api/types"

function planSummary(overrides: Partial<ProposalSummary> = {}): ProposalSummary {
  return {
    operation_type: "create_plan",
    operation_label: "创建定投",
    title: "创建定投计划 005827（默认停用）",
    fund_code: "005827",
    fund_name: "易方达蓝筹精选",
    action: "buy",
    action_label: "买入",
    date: "2026-01-02",
    amount: 1000,
    shares: null,
    nav: null,
    fee: null,
    channel: "",
    is_t1: false,
    note: "",
    warnings: [],
    cadence: "week",
    day_of_week: 3,
    day_of_month: null,
    ...overrides,
  } as ProposalSummary
}

describe("operationLabel", () => {
  it("中文返回中文操作名，英文返回英文操作名", () => {
    mocks.lang = "zh"
    expect(operationLabel("add_transaction")).toBe("新增交易")
    expect(operationLabel("execute_plan")).toBe("手动执行定投")
    mocks.lang = "en"
    expect(operationLabel("add_transaction")).toBe("Add transaction")
    expect(operationLabel("execute_plan")).toBe("Run auto-invest")
  })

  it("未知操作类型回退到原始 code", () => {
    expect(operationLabel("mystery_op")).toBe("mystery_op")
  })
})

describe("cadenceLabel / planScheduleLabel", () => {
  it("cadence 中英文", () => {
    mocks.lang = "zh"
    expect(cadenceLabel("biweek")).toBe("每两周")
    mocks.lang = "en"
    expect(cadenceLabel("biweek")).toBe("Bi-weekly")
  })

  it("排期按 cadence/day_of_week/day_of_month 重拼，中英文", () => {
    mocks.lang = "zh"
    expect(planScheduleLabel(planSummary())).toBe("每周四")
    expect(planScheduleLabel(planSummary({ cadence: "biweek" }))).toBe("每两周的周四")
    expect(
      planScheduleLabel(planSummary({ cadence: "month", day_of_week: null, day_of_month: 15 })),
    ).toBe("每月15日")
    mocks.lang = "en"
    expect(planScheduleLabel(planSummary())).toBe("Weekly on Thu")
    expect(planScheduleLabel(planSummary({ cadence: "biweek" }))).toBe("Bi-weekly on Thu")
    expect(
      planScheduleLabel(planSummary({ cadence: "month", day_of_week: null, day_of_month: 15 })),
    ).toBe("Monthly on day 15")
  })

  it("仅 daily 时回退到频率标签", () => {
    mocks.lang = "zh"
    expect(
      planScheduleLabel(planSummary({ cadence: "daily", day_of_week: null })),
    ).toBe("每日")
  })
})

describe("feeSourceLabel / alertTypeLabel", () => {
  it("fee_source 中英文，空值返回空串", () => {
    mocks.lang = "zh"
    expect(feeSourceLabel("fetched")).toBe("抓取费率")
    expect(feeSourceLabel("needs_fee")).toBe("需提供手续费")
    expect(feeSourceLabel(null)).toBe("")
    mocks.lang = "en"
    expect(feeSourceLabel("fetched")).toBe("Fetched rate")
    expect(feeSourceLabel("existing")).toBe("Existing fee")
  })

  it("alert_type 中英文，空值返回破折号", () => {
    mocks.lang = "zh"
    expect(alertTypeLabel("dividend")).toBe("分红提醒")
    expect(alertTypeLabel("stop_loss")).toBe("止损提醒")
    expect(alertTypeLabel(undefined)).toBe("—")
    mocks.lang = "en"
    expect(alertTypeLabel("take_profit")).toBe("Take-profit alert")
  })
})

describe("proposalTitle", () => {
  beforeEach(() => {
    mocks.lang = "zh"
  })

  it("交易类：动词+方向+代码", () => {
    expect(proposalTitle(planSummary({ operation_type: "add_transaction" }))).toBe("买入 005827")
    expect(
      proposalTitle(
        planSummary({ operation_type: "delete_transaction", action: "sell" }),
      ),
    ).toBe("删除 卖出 005827")
    mocks.lang = "en"
    expect(proposalTitle(planSummary({ operation_type: "add_transaction" }))).toBe("Buy 005827")
    expect(
      proposalTitle(
        planSummary({ operation_type: "delete_transaction", action: "sell" }),
      ),
    ).toBe("Delete Sell 005827")
  })

  it("计划类：含计划编号", () => {
    expect(proposalTitle(planSummary({ operation_type: "update_plan", plan_id: 7 }))).toBe(
      "修改定投计划 #7",
    )
    expect(
      proposalTitle(planSummary({ operation_type: "toggle_plan", plan_id: 7, enabled_after: false })),
    ).toBe("停用定投计划 #7")
    mocks.lang = "en"
    expect(proposalTitle(planSummary({ operation_type: "update_plan", plan_id: 7 }))).toBe(
      "Update auto-invest plan #7",
    )
    expect(
      proposalTitle(planSummary({ operation_type: "toggle_plan", plan_id: 7, enabled_after: false })),
    ).toBe("Disable auto-invest plan #7")
  })

  it("批量/回填：含条数", () => {
    mocks.lang = "zh"
    expect(proposalTitle(planSummary({ operation_type: "batch_import", count: 12 }))).toBe(
      "批量导入 12 条交易",
    )
    expect(
      proposalTitle(planSummary({ operation_type: "backfill_transaction_navs", count: 5 })),
    ).toBe("回填净值 5 条")
    mocks.lang = "en"
    expect(proposalTitle(planSummary({ operation_type: "batch_import", count: 12 }))).toBe(
      "Batch import 12 transactions",
    )
  })

  it("提醒处理：含提醒类型与编号", () => {
    mocks.lang = "zh"
    expect(
      proposalTitle(
        planSummary({ operation_type: "resolve_alert", alert_type: "dividend", alert_id: 9 }),
      ),
    ).toBe("处理分红提醒 #9")
    mocks.lang = "en"
    expect(
      proposalTitle(
        planSummary({ operation_type: "resolve_alert", alert_type: "dividend", alert_id: 9 }),
      ),
    ).toBe("Resolve Dividend alert #9")
  })

  it("转换类：两腿代码", () => {
    mocks.lang = "en"
    expect(
      proposalTitle(
        planSummary({
          operation_type: "add_conversion",
          fund_code: "000001",
          conversion: { from: { fund_code: "000001" } as never, to: { fund_code: "000002" } as never },
        }),
      ),
    ).toBe("Convert 000001 → 000002")
  })
})
