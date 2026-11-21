import { beforeEach, describe, expect, it, vi } from "vitest"
import { act, render } from "@testing-library/react"
import { LanguageProvider } from "@/i18n/LanguageContext"
import { ChatProvider, useChat } from "./ChatContext"

const mocks = vi.hoisted(() => ({
  getSystemPrompt: vi.fn(),
  getAIUsage: vi.fn(),
  streamChat: vi.fn(),
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
  mocks.streamChat.mockReset().mockImplementation((_msgs: unknown, cb: (c: Chunk) => void) => {
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