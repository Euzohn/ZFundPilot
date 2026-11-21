import { beforeEach, describe, expect, it, vi } from "vitest"

const mocks = vi.hoisted(() => ({ lang: "zh" as "zh" | "en" }))
vi.mock("@/i18n/LanguageContext", () => ({
  getCurrentLang: () => mocks.lang,
}))

import {
  translateAdviceMetric,
  translateAdviceRisk,
  translateBackendError,
  translateSimulationMetric,
  translateSimulationRule,
} from "./backendLabels"

beforeEach(() => {
  mocks.lang = "zh"
})

describe("action item metric labels", () => {
  it("maps known metric codes zh/en", () => {
    expect(translateAdviceMetric("max_single_weight")).toBe("最大单基金占比")
    mocks.lang = "en"
    expect(translateAdviceMetric("max_single_weight")).toBe("Largest fund weight")
  })

  it("falls back to raw code when unknown", () => {
    expect(translateAdviceMetric("unknown_metric")).toBe("unknown_metric")
  })

  it("simulation metric allocation_score label", () => {
    expect(translateSimulationMetric("allocation_score")).toBe("体检配置分")
    mocks.lang = "en"
    expect(translateSimulationMetric("allocation_score")).toBe("Allocation score")
  })
})

describe("simulation rule labels", () => {
  it("equity_to_bond disambiguates by side", () => {
    const eq = translateSimulationRule("equity_to_bond", { target: 0.7, side: "equity" })
    const bond = translateSimulationRule("equity_to_bond", { target: 0.1, side: "bond" })
    expect(eq).toContain("权益类降至 70%")
    expect(bond).toContain("债券型提升至 10%")
    expect(eq).not.toBe(bond)
  })

  it("equity_to_bond defaults to equity side when side missing", () => {
    expect(translateSimulationRule("equity_to_bond", { target: 0.7 }))
      .toContain("权益类降至 70%")
  })

  it("interpolates fund name / sector / target", () => {
    expect(translateSimulationRule("reduce_single_fund", { name: "Fund A", target: 0.4 }))
      .toContain("Fund A")
    expect(translateSimulationRule("reduce_single_fund", { name: "Fund A", target: 0.4 }))
      .toContain("40%")
    expect(translateSimulationRule("reduce_sector", { sector: "半导体", target: 0.2 }))
      .toContain("半导体")
  })

  it("english interpolation", () => {
    mocks.lang = "en"
    expect(translateSimulationRule("reduce_qdii", { target: 0.3 }))
      .toContain("30%")
  })

  it("falls back to raw code when unknown", () => {
    expect(translateSimulationRule("nope", {})).toBe("nope")
  })
})

describe("advice risk labels", () => {
  it("data_stale interpolates counts", () => {
    const text = translateAdviceRisk({ code: "data_stale", params: { stale: 2, missing: 1 } })
    expect(text).toContain("2 只")
    expect(text).toContain("1 只")
  })

  it("data_stale defaults counts to 0 when params missing", () => {
    expect(translateAdviceRisk({ code: "data_stale" })).toContain("0 只")
  })

  it("static disclaimer codes", () => {
    expect(translateAdviceRisk({ code: "not_investment_advice" }))
      .toContain("不构成投资建议")
    mocks.lang = "en"
    expect(translateAdviceRisk({ code: "simulation_unavailable" }))
      .toContain("Not enough holdings")
  })

  it("falls back to raw code when unknown", () => {
    expect(translateAdviceRisk({ code: "unknown_risk" })).toBe("unknown_risk")
  })
})

describe("translateBackendError 登录限流 429 i18n", () => {
  it("含可变秒数的限流消息前缀匹配，英文不再泄漏中文", () => {
    mocks.lang = "en"
    expect(translateBackendError("尝试次数过多，请 30 秒后再试"))
      .toBe("Too many attempts, please try again later")
  })

  it("中文保持通用措辞（与后端一致）", () => {
    mocks.lang = "zh"
    expect(translateBackendError("尝试次数过多，请 30 秒后再试"))
      .toBe("尝试次数过多，请稍后再试")
    expect(translateBackendError("尝试次数过多，请稍后再试"))
      .toBe("尝试次数过多，请稍后再试")
  })

  it("去掉 Error: 前缀后仍可匹配", () => {
    mocks.lang = "en"
    expect(translateBackendError("Error: 尝试次数过多，请 5 秒后再试"))
      .toBe("Too many attempts, please try again later")
  })
})
