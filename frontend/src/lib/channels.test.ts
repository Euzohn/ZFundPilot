import { beforeEach, describe, expect, it, vi } from "vitest"

const mocks = vi.hoisted(() => ({
  getPreferences: vi.fn(),
  savePreferences: vi.fn(),
}))
vi.mock("@/api/client", () => ({ api: mocks }))

import {
  getChannels,
  getChannelsAsync,
  invalidateChannelsCache,
} from "./channels"
import {
  getChannelColors,
  getChannelColorsAsync,
  invalidateChannelColorsCache,
} from "./channelColors"

const CH_KEY = "zfundpilot_channels"
const CC_KEY = "zfundpilot_channel_colors"

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  // 每个用例前重置模块缓存，避免跨用例污染
  invalidateChannelsCache()
  invalidateChannelColorsCache()
})

describe("invalidateChannelsCache", () => {
  it("首次异步加载后缓存服务端值，失效后重读恢复后的新值", async () => {
    mocks.getPreferences.mockResolvedValue({ channels: JSON.stringify(["支付宝", "银行"]) })
    expect(await getChannelsAsync()).toEqual(["支付宝", "银行"])

    // 模拟备份恢复替换了服务端 preferences；未失效时仍读旧缓存
    mocks.getPreferences.mockResolvedValue({ channels: JSON.stringify(["券商", "其它"]) })
    expect(await getChannelsAsync()).toEqual(["支付宝", "银行"])

    invalidateChannelsCache()
    expect(await getChannelsAsync()).toEqual(["券商", "其它"])
    // 失效不应回写服务端（纯读刷新）
    expect(mocks.savePreferences).not.toHaveBeenCalled()
  })

  it("失效清空 localStorage，同步 getter 不再返回陈旧缓存", async () => {
    mocks.getPreferences.mockResolvedValue({ channels: JSON.stringify(["支付宝"]) })
    await getChannelsAsync()
    expect(JSON.parse(localStorage.getItem(CH_KEY)!)).toEqual(["支付宝"])

    invalidateChannelsCache()
    expect(localStorage.getItem(CH_KEY)).toBeNull()
    // 同步 getter 回退默认渠道（含 7 项），而非陈旧单项缓存
    expect(getChannels().length).toBeGreaterThan(1)
  })
})

describe("invalidateChannelColorsCache", () => {
  it("失效后重读恢复后的服务端配色，且不回写服务端", async () => {
    mocks.getPreferences.mockResolvedValue({ channel_colors: JSON.stringify({ "支付宝": "#111111" }) })
    expect(await getChannelColorsAsync()).toEqual({ "支付宝": "#111111" })

    mocks.getPreferences.mockResolvedValue({ channel_colors: JSON.stringify({ "支付宝": "#222222" }) })
    expect(await getChannelColorsAsync()).toEqual({ "支付宝": "#111111" })

    invalidateChannelColorsCache()
    expect(await getChannelColorsAsync()).toEqual({ "支付宝": "#222222" })
    expect(mocks.savePreferences).not.toHaveBeenCalled()
    expect(localStorage.getItem(CC_KEY)).not.toBeNull() // 重读后重新缓存
  })

  it("失效清空 localStorage 配色缓存", async () => {
    mocks.getPreferences.mockResolvedValue({ channel_colors: JSON.stringify({ "支付宝": "#111111" }) })
    await getChannelColorsAsync()
    invalidateChannelColorsCache()
    expect(localStorage.getItem(CC_KEY)).toBeNull()
    expect(getChannelColors()["支付宝"]).toBe("#3b82f6") // 回退默认配色
  })
})