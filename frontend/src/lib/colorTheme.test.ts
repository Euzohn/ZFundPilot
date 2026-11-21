import { beforeEach, describe, expect, it, vi } from "vitest"
import { readFileSync } from "node:fs"
import { resolve } from "node:path"

const mocks = vi.hoisted(() => ({
  getPreferences: vi.fn(),
  savePreferences: vi.fn(),
}))
vi.mock("@/api/client", () => ({ api: mocks }))

import {
  applyColorTheme,
  getColorTheme,
  getColorThemeAsync,
  saveColorTheme,
} from "./colorTheme"

const KEY = "zfundpilot_color_theme"

describe("getColorTheme", () => {
  it("默认国际惯例，读取本地存储", () => {
    expect(getColorTheme()).toBe("international")
    localStorage.setItem(KEY, "china")
    expect(getColorTheme()).toBe("china")
  })

  it("localStorage 读取抛错时回退默认", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("storage disabled")
    })
    expect(getColorTheme()).toBe("international")
  })
})

describe("saveColorTheme", () => {
  it("写入本地并同步服务端", async () => {
    mocks.savePreferences.mockResolvedValue(undefined)
    await saveColorTheme("china")
    expect(localStorage.getItem(KEY)).toBe("china")
    expect(mocks.savePreferences).toHaveBeenCalledWith({ color_theme: "china" })
  })

  it("本地写入失败（配额/隐私模式）仍尝试服务端同步", async () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota exceeded")
    })
    mocks.savePreferences.mockResolvedValue(undefined)
    await expect(saveColorTheme("china")).resolves.toBeUndefined()
    expect(mocks.savePreferences).toHaveBeenCalledWith({ color_theme: "china" })
  })

  it("服务端失败不抛错，本地已写入", async () => {
    mocks.savePreferences.mockRejectedValue(new Error("network"))
    await expect(saveColorTheme("international")).resolves.toBeUndefined()
    expect(localStorage.getItem(KEY)).toBe("international")
  })
})

describe("getColorThemeAsync", () => {
  it("服务端值优先并写入本地", async () => {
    mocks.getPreferences.mockResolvedValue({ color_theme: "china" })
    expect(await getColorThemeAsync()).toBe("china")
    expect(localStorage.getItem(KEY)).toBe("china")
  })

  it("服务端失败/非法值回退本地", async () => {
    localStorage.setItem(KEY, "china")
    mocks.getPreferences.mockRejectedValue(new Error("network"))
    expect(await getColorThemeAsync()).toBe("china")
    mocks.getPreferences.mockResolvedValue({ color_theme: "bogus" })
    expect(await getColorThemeAsync()).toBe("china")
  })
})

describe("applyColorTheme", () => {
  it("china 加类，international 移除", () => {
    applyColorTheme("china")
    expect(document.documentElement.classList.contains("color-theme-cn")).toBe(true)
    applyColorTheme("international")
    expect(document.documentElement.classList.contains("color-theme-cn")).toBe(false)
  })
})

describe("index.html 首屏预置脚本", () => {
  const html = readFileSync(resolve(__dirname, "../../index.html"), "utf-8")
  const script = html.match(/<script>([\s\S]*?)<\/script>/)?.[1]

  beforeEach(() => {
    document.documentElement.className = ""
  })

  it("内联脚本读取 zfundpilot_color_theme", () => {
    expect(script).toBeTruthy()
    expect(script).toContain("zfundpilot_color_theme")
  })

  it("china 在首屏前加 color-theme-cn 类", () => {
    localStorage.setItem(KEY, "china")
    new Function(script!)()
    expect(document.documentElement.classList.contains("color-theme-cn")).toBe(true)
  })

  it("国际惯例/未设置不加类", () => {
    new Function(script!)()
    expect(document.documentElement.classList.contains("color-theme-cn")).toBe(false)
    localStorage.setItem(KEY, "international")
    new Function(script!)()
    expect(document.documentElement.classList.contains("color-theme-cn")).toBe(false)
  })

  it("保留 ui_theme 暗色预置", () => {
    localStorage.setItem("zfundpilot_ui_theme", "dark")
    new Function(script!)()
    expect(document.documentElement.classList.contains("dark")).toBe(true)
  })

  it("localStorage 不可用时不抛错", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("storage disabled")
    })
    expect(() => new Function(script!)()).not.toThrow()
    expect(document.documentElement.classList.contains("color-theme-cn")).toBe(false)
  })

  it("ui_theme 分支抛错不影响涨跌配色预置", () => {
    localStorage.setItem(KEY, "china")
    vi.spyOn(window, "matchMedia").mockImplementation(() => {
      throw new Error("matchMedia unavailable")
    })
    new Function(script!)()
    expect(document.documentElement.classList.contains("color-theme-cn")).toBe(true)
  })
})