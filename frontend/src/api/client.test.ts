import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "./client"
import { getCurrentLang } from "@/i18n/LanguageContext"

vi.mock("@/i18n/LanguageContext", () => ({ getCurrentLang: vi.fn(() => "zh") }))

const fetchMock = vi.fn()
const reloadMock = vi.fn()

function jsonResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: `Status ${status}`,
    text: async () => JSON.stringify(body),
    json: async () => body,
  }
}

function textResponse(status: number, text: string) {
  return {
    ok: false,
    status,
    statusText: `Status ${status}`,
    text: async () => text,
    json: async () => {
      throw new Error("not json")
    },
  }
}

beforeEach(() => {
  vi.mocked(getCurrentLang).mockReturnValue("zh")
  fetchMock.mockReset()
  reloadMock.mockReset()
  vi.stubGlobal("fetch", fetchMock)
  // jsdom 的 location.reload 未实现导航，替换为可断言的 mock
  Object.defineProperty(window, "location", {
    configurable: true,
    writable: true,
    value: { href: "http://localhost/", reload: reloadMock },
  })
  localStorage.setItem("zfundpilot_token", "tok")
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("request 401 处理", () => {
  it("登录接口 401 不清 token、不刷新页面，抛出解析后的错误供登录页展示", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(401, { detail: "用户名或密码错误" }))
    await expect(api.login("user", "wrong")).rejects.toMatchObject({
      message: "用户名或密码错误",
      status: 401,
      body: { detail: "用户名或密码错误" },
    })
    expect(reloadMock).not.toHaveBeenCalled()
    expect(localStorage.getItem("zfundpilot_token")).toBe("tok")
  })

  it("非登录接口 401 清 token 并刷新页面引导重新登录", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(401, { detail: "未登录" }))
    await expect(api.getMe()).rejects.toThrow("未登录或登录已过期")
    expect(reloadMock).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem("zfundpilot_token")).toBeNull()
  })

  it("英文环境 401 文案为英文", async () => {
    vi.mocked(getCurrentLang).mockReturnValue("en")
    fetchMock.mockResolvedValueOnce(jsonResponse(401, {}))
    await expect(api.getMe()).rejects.toThrow("Not authenticated or session expired")
  })
})

describe("错误对象附带 status/body/code", () => {
  it("409 detail 解析：下游可用 err.status === 409 识别重复执行", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(409, { detail: "该定投计划今日已执行" }))
    await expect(api.executeAutoInvestPlan(1)).rejects.toMatchObject({
      message: "该定投计划今日已执行",
      status: 409,
      body: { detail: "该定投计划今日已执行" },
    })
  })

  it("error.message/error.code 结构", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(400, { error: { message: "参数错误", code: "BAD_PARAM" } }))
    await expect(api.getSummary()).rejects.toMatchObject({
      message: "参数错误",
      code: "BAD_PARAM",
      status: 400,
    })
  })

  it("detail 为对象时取 message/code", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(422, { detail: { message: "字段校验失败", code: "INVALID" } }))
    await expect(api.getSummary()).rejects.toMatchObject({
      message: "字段校验失败",
      code: "INVALID",
      status: 422,
    })
  })

  it("非 JSON 错误体回退原文，仍附带 status", async () => {
    fetchMock.mockResolvedValueOnce(textResponse(500, "Internal Server Error"))
    await expect(api.getSummary()).rejects.toMatchObject({
      message: "Internal Server Error",
      status: 500,
      body: undefined,
    })
  })
})

describe("streamChat 错误解析", () => {
  it("非 2xx 解析 detail 而非抛出原始 JSON", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(503, { detail: "AI 服务不可用" }))
    await expect(api.streamChat([{ role: "user", content: "hi" }], vi.fn())).rejects.toMatchObject({
      message: "AI 服务不可用",
      status: 503,
    })
  })

  it("非 2xx 解析 error.message", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(429, { error: { message: "请求过于频繁" } }))
    await expect(api.streamChat([{ role: "user", content: "hi" }], vi.fn())).rejects.toMatchObject({
      message: "请求过于频繁",
      status: 429,
    })
  })

  it("401 仍走清 token + 刷新", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(401, {}))
    await expect(api.streamChat([{ role: "user", content: "hi" }], vi.fn())).rejects.toThrow("未登录或登录已过期")
    expect(reloadMock).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem("zfundpilot_token")).toBeNull()
  })
})

describe("downloadWithAuth", () => {
  it("401 清 token 并刷新页面（与其他路径一致）", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(401, { detail: "未登录" }))
    await expect(api.downloadTemplate()).rejects.toThrow("未登录或登录已过期")
    expect(reloadMock).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem("zfundpilot_token")).toBeNull()
  })

  it("非 401 错误解析 detail", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(500, { detail: "导出失败" }))
    await expect(api.exportCsv()).rejects.toMatchObject({ message: "导出失败", status: 500 })
    expect(reloadMock).not.toHaveBeenCalled()
  })

  it("成功时触发浏览器下载", async () => {
    const createObjectURL = vi.fn(() => "blob:mock")
    const revokeObjectURL = vi.fn()
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL, revokeObjectURL }))
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {})
    fetchMock.mockResolvedValueOnce({ ok: true, status: 200, blob: async () => new Blob(["a,b"]) })
    await api.downloadTemplate()
    expect(createObjectURL).toHaveBeenCalledTimes(1)
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:mock")
    expect(clickSpy).toHaveBeenCalledTimes(1)
    clickSpy.mockRestore()
  })
})

describe("parseCsv / parseScreenshot 错误解析", () => {
  it("parseCsv 非 2xx 解析 detail", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(400, { detail: "CSV 格式错误" }))
    const file = new File(["a,b"], "t.csv", { type: "text/csv" })
    await expect(api.parseCsv(file)).rejects.toMatchObject({ message: "CSV 格式错误", status: 400 })
  })

  it("parseScreenshot 非 2xx 解析 error.message", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(400, { error: { message: "图片识别失败" } }))
    await expect(api.parseScreenshot(new Blob(["x"]), "transactions")).rejects.toMatchObject({
      message: "图片识别失败",
      status: 400,
    })
  })
})

describe("fetchFundMeta URL 编码", () => {
  it("特殊字符经 encodeURIComponent 编码，避免破坏路由", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, {}))
    await api.fetchFundMeta("000001/?x")
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/funds/000001%2F%3Fx/fetch",
      expect.objectContaining({ method: "POST" }),
    )
  })

  it("正常基金代码路径不变", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, {}))
    await api.fetchFundMeta("000001")
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/funds/000001/fetch",
      expect.objectContaining({ method: "POST" }),
    )
  })
})

describe("422 数组 detail 可读化", () => {
  it("FastAPI 校验错误数组拼接各 msg，不把原始 JSON 甩给用户", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(422, {
      detail: [
        { loc: ["body", "new_password"], msg: "新密码过长（UTF-8 编码不能超过 72 字节）", type: "value_error" },
        { loc: ["body", "x"], msg: "字段必填", type: "missing" },
      ],
    }))
    await expect(api.changePassword("old", "x".repeat(73))).rejects.toMatchObject({
      message: "新密码过长（UTF-8 编码不能超过 72 字节）; 字段必填",
      status: 422,
    })
  })

  it("数组元素缺 msg 时跳过，全空则回退 JSON", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(422, { detail: [{ type: "missing" }] }))
    await expect(api.getSummary()).rejects.toMatchObject({ status: 422 })
  })
})

describe("uploadWithAuth 统一错误解析", () => {
  const zip = () => new File(["x"], "b.zip", { type: "application/zip" })

  it("error.message/code/status 与 request 路径一致（此前内联解析丢失 code/status）", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(400, { error: { message: "备份格式无效", code: "BAD_BACKUP" } }))
    await expect(api.preflightBackup(zip())).rejects.toMatchObject({
      message: "备份格式无效", code: "BAD_BACKUP", status: 400,
    })
  })

  it("422 数组 detail 同样可读化", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(422, { detail: [{ msg: "文件为空", type: "value_error" }] }))
    await expect(api.restoreBackup(zip(), "RESTORE")).rejects.toMatchObject({
      message: "文件为空", status: 422,
    })
  })

  it("401 清 token 并刷新页面", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(401, {}))
    await expect(api.preflightBackup(zip())).rejects.toThrow("未登录或登录已过期")
    expect(reloadMock).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem("zfundpilot_token")).toBeNull()
  })
})
