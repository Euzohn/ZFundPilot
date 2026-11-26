import { beforeEach, describe, expect, it, vi } from "vitest"
import { act, render } from "@testing-library/react"
import { LanguageProvider } from "@/i18n/LanguageContext"
import { ChatProvider, extractToolCall, useChat } from "./ChatContext"

const mocks = vi.hoisted(() => ({
  getSystemPrompt: vi.fn(),
  getAIUsage: vi.fn(),
  streamChat: vi.fn(),
  addTransaction: vi.fn(),
}))

vi.mock("@/api/client", () => ({ api: mocks }))

type Chunk = {
  content?: string
  status?: string
  error?: string
  done?: boolean
  usage?: { prompt: number; completion: number; total: number }
}

let ctx: ReturnType<typeof useChat>
function Probe() {
  ctx = useChat()
  return null
}

function renderChat() {
  render(
    <LanguageProvider>
      <ChatProvider>
        <Probe />
      </ChatProvider>
    </LanguageProvider>,
  )
}

const B_MESSAGES = [{ role: "user" as const, content: "历史消息" }]

// 活动会话 A（空消息）+ 归档会话 B（1 条消息）：
// A 发送后 aiIndex=1，切到 B 后该下标越界，可复现旧代码的 updater 崩溃
function seedSessions() {
  localStorage.setItem("zfundpilot_chat_sessions", JSON.stringify({
    activeId: "chat-a",
    activeTitle: "会话A",
    activeMessages: [],
    activeTxStatus: {},
    activeSystemPrompt: "sys",
    includeContext: true,
    archive: [{
      id: "chat-b",
      title: "会话B",
      messages: B_MESSAGES,
      txStatus: {},
      systemPrompt: "sys",
      updatedAt: "2026-02-10T10:00:00.000Z",
    }],
  }))
}

let onChunk: ((c: Chunk) => void) | null = null
let finishStream: (() => void) | null = null
let failStream: ((e: Error) => void) | null = null

beforeEach(() => {
  mocks.getSystemPrompt.mockReset().mockResolvedValue({ system_prompt: "sys" })
  mocks.getAIUsage.mockReset().mockResolvedValue({ today: 0, total: 0, recent: [] })
  mocks.addTransaction.mockReset().mockResolvedValue({ id: 9 })
  mocks.streamChat.mockReset().mockImplementation((_msgs: unknown, _sentAt: string, cb: (c: Chunk) => void) => {
    onChunk = cb
    return new Promise<void>((resolve, reject) => {
      finishStream = resolve
      failStream = reject
    })
  })
  onChunk = null
  finishStream = null
  failStream = null
  seedSessions()
})

describe("ChatContext 流式期间会话守卫", () => {
  it("streaming 期间 handleSwitchChat/handleNewChat 不生效，流式写入正常", async () => {
    renderChat()
    await act(async () => { ctx.handleSend("你好") })
    expect(ctx.streaming).toBe(true)
    expect(ctx.messages).toHaveLength(2)

    act(() => { ctx.handleSwitchChat("chat-b") })
    expect(ctx.activeId).toBe("chat-a")
    expect(ctx.messages).toHaveLength(2)

    act(() => { ctx.handleNewChat() })
    expect(ctx.activeId).toBe("chat-a")
    expect(ctx.messages).toHaveLength(2)
    expect(ctx.archive).toHaveLength(1)

    // 守卫不影响正常流式写入
    act(() => { onChunk!({ content: "回复" }) })
    act(() => { onChunk!({ content: "内容" }) })
    expect(ctx.messages[1]).toEqual({ role: "assistant", content: "回复内容" })

    await act(async () => { finishStream!() })
    expect(ctx.streaming).toBe(false)

    // 流式结束后切换恢复正常
    act(() => { ctx.handleSwitchChat("chat-b") })
    expect(ctx.activeId).toBe("chat-b")
    expect(ctx.messages).toEqual(B_MESSAGES)
  })

  it("同 tick 竞态切换会话后，onChunk 不崩溃也不污染目标会话（aiIndex 兜底）", async () => {
    renderChat()
    // 同一渲染闭包内连续调用：handleSwitchChat 的 streaming 还是 false，切换会生效，
    // 此时 B 只有 1 条消息而 aiIndex=1 —— 旧代码在 updater 内读 undefined.content 崩溃
    await act(async () => {
      ctx.handleSend("你好")
      ctx.handleSwitchChat("chat-b")
    })
    expect(ctx.activeId).toBe("chat-b")

    act(() => { onChunk!({ content: "串流内容" }) })
    expect(ctx.messages).toEqual(B_MESSAGES)

    act(() => { onChunk!({ error: "boom" }) })
    expect(ctx.messages).toEqual(B_MESSAGES)

    await act(async () => { finishStream!() })
    expect(ctx.streaming).toBe(false)
    expect(ctx.messages).toEqual(B_MESSAGES)
  })

  it("同 tick 竞态切换后 streamChat 抛错，catch 分支同样不崩溃不污染", async () => {
    renderChat()
    await act(async () => {
      ctx.handleSend("你好")
      ctx.handleSwitchChat("chat-b")
    })
    expect(ctx.activeId).toBe("chat-b")

    await act(async () => { failStream!(new Error("网络错误")) })
    expect(ctx.streaming).toBe(false)
    expect(ctx.messages).toEqual(B_MESSAGES)
  })

  it("未切换会话时错误正常写入 AI 消息", async () => {
    renderChat()
    await act(async () => { ctx.handleSend("你好") })
    await act(async () => { failStream!(new Error("网络错误")) })
    expect(ctx.streaming).toBe(false)
    expect(ctx.messages[1].role).toBe("assistant")
    expect(ctx.messages[1].content).toContain("请求失败")
  })
})

describe("ChatContext 确认交易 payload", () => {
  const baseTx = {
    fund_code: "000001", action: "sell", date: "2026-01-05",
    amount: null, shares: 500, nav: null, fee: 0, channel: "支付宝", note: "测试备注",
  }

  it("盘后(T+1)提交携带 is_t1，备注不再拼接 T+1 文案", async () => {
    renderChat()
    await act(async () => { ctx.handleConfirmTx(0, { ...baseTx, after_three: true }) })
    const payload = mocks.addTransaction.mock.calls[0][0]
    expect(payload).toEqual(expect.objectContaining({
      fund_code: "000001", action: "sell", date: "2026-01-05",
      is_t1: true, note: "测试备注",
    }))
    expect(payload.note).not.toMatch(/T\+1/)
  })

  it("盘中提交 is_t1 为 false", async () => {
    renderChat()
    await act(async () => { ctx.handleConfirmTx(0, { ...baseTx, after_three: false }) })
    expect(mocks.addTransaction.mock.calls[0][0]).toEqual(
      expect.objectContaining({ is_t1: false }))
  })
})

describe("extractToolCall 数值字段 NaN 守卫", () => {
  const wrap = (obj: Record<string, unknown>) =>
    "```json\n" + JSON.stringify({ tool: "add_transaction", ...obj }) + "\n```"

  it("非法数值（字符串/对象）归一为 null，不传播 NaN", () => {
    const tx = extractToolCall(wrap({
      fund_code: "000001", action: "buy", date: "2026-01-05",
      amount: "abc", shares: {}, nav: "n/a", fee: "xyz",
    }))
    expect(tx).not.toBeNull()
    expect(tx!.amount).toBeNull()
    expect(tx!.shares).toBeNull()
    expect(tx!.nav).toBeNull()
    expect(tx!.fee).toBe(0)
  })

  it("合法数值正常解析", () => {
    const tx = extractToolCall(wrap({
      fund_code: "000001", action: "buy", date: "2026-01-05",
      amount: 1000, shares: null, nav: 1.5, fee: 2.5,
    }))
    expect(tx!.amount).toBe(1000)
    expect(tx!.shares).toBeNull()
    expect(tx!.nav).toBe(1.5)
    expect(tx!.fee).toBe(2.5)
  })

  it("Infinity 也归一为 null（非有限数）", () => {
    const tx = extractToolCall(wrap({
      fund_code: "000001", action: "buy", date: "2026-01-05", amount: Infinity,
    }))
    expect(tx!.amount).toBeNull()
  })
})

it("每轮发送只携带一次时间，历史消息保留原文", async () => {
  vi.useFakeTimers({ toFake: ["Date"] })
  try {
    vi.setSystemTime(new Date("2026-11-26T15:59:00Z"))
    renderChat()
    await act(async () => { ctx.handleSend("今天的行情") })
    act(() => { onChunk!({ content: "回答" }) })
    await act(async () => { finishStream!() })

    vi.setSystemTime(new Date("2026-11-26T16:01:00Z"))
    await act(async () => { ctx.handleSend("昨天的呢") })
    await act(async () => { finishStream!() })

    expect(mocks.streamChat).toHaveBeenNthCalledWith(1, [
      { role: "system", content: "sys" },
      { role: "user", content: "今天的行情" },
    ], "2026-11-26T15:59:00.000Z", expect.any(Function))
    expect(mocks.streamChat).toHaveBeenNthCalledWith(2, [
      { role: "system", content: "sys" },
      { role: "user", content: "今天的行情" },
      { role: "assistant", content: "回答" },
      { role: "user", content: "昨天的呢" },
    ], "2026-11-26T16:01:00.000Z", expect.any(Function))
    expect(ctx.messages[2].content).toBe("昨天的呢")
  } finally {
    vi.useRealTimers()
  }
})
