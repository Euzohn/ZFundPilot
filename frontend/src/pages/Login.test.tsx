import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { fireEvent, render, screen } from "@testing-library/react"
import { Toaster } from "sonner"
import { LanguageProvider } from "@/i18n/LanguageContext"
import Login from "./Login"

// 不 mock api/client：走真实 request()，端到端验证登录 401 不再触发整页刷新、错误可见
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

function renderLogin(onSuccess = vi.fn()) {
  render(
    <LanguageProvider>
      <Login onSuccess={onSuccess} />
      <Toaster />
    </LanguageProvider>,
  )
  return onSuccess
}

function fillAndSubmit() {
  fireEvent.change(screen.getByLabelText("请输入用户名"), { target: { value: "admin" } })
  fireEvent.change(screen.getByLabelText("请输入访问密码"), { target: { value: "wrong-pass" } })
  fireEvent.click(screen.getByRole("button", { name: "登录" }))
}

beforeEach(() => {
  fetchMock.mockReset()
  reloadMock.mockReset()
  vi.stubGlobal("fetch", fetchMock)
  // jsdom 的 location.reload 未实现导航，替换为可断言的 mock
  Object.defineProperty(window, "location", {
    configurable: true,
    writable: true,
    value: { href: "http://localhost/", reload: reloadMock },
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("Login 失败反馈", () => {
  it("401 用户名/密码错误：不刷新页面，toast 与密码字段级错误均可见", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(401, { detail: "用户名或密码错误" }))
    const onSuccess = renderLogin()
    fillAndSubmit()

    // 字段级错误（role=alert）与 toast 同时展示
    expect(await screen.findByRole("alert")).toHaveTextContent("用户名或密码错误")
    expect(await screen.findByText(/密码错误，请重试: 用户名或密码错误/)).toBeInTheDocument()
    expect(reloadMock).not.toHaveBeenCalled()
    expect(onSuccess).not.toHaveBeenCalled()
    expect(localStorage.getItem("zfundpilot_token")).toBeNull()
    // 失败后按钮恢复可用，允许再次尝试
    expect(screen.getByRole("button", { name: "登录" })).not.toBeDisabled()
  })

  it("429 限流：toast 提示但不误标密码字段错误", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(429, { detail: "尝试次数过多，请稍后再试" }))
    renderLogin()
    fillAndSubmit()

    expect(await screen.findByText(/密码错误，请重试: 尝试次数过多，请稍后再试/)).toBeInTheDocument()
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
    expect(reloadMock).not.toHaveBeenCalled()
  })

  it("修改密码输入后清除字段级错误", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(401, { detail: "用户名或密码错误" }))
    renderLogin()
    fillAndSubmit()

    expect(await screen.findByRole("alert")).toHaveTextContent("用户名或密码错误")
    fireEvent.change(screen.getByLabelText("请输入访问密码"), { target: { value: "new-pass" } })
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
  })
})

describe("Login 成功路径", () => {
  it("登录成功写入 token 并回调 onSuccess", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { ok: true, token: "tok-1", message: "" }))
    const onSuccess = renderLogin()
    fillAndSubmit()

    await screen.findByText(/登录成功/)
    expect(localStorage.getItem("zfundpilot_token")).toBe("tok-1")
    expect(onSuccess).toHaveBeenCalledTimes(1)
    expect(reloadMock).not.toHaveBeenCalled()
  })
})