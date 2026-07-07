import { useState, useEffect, useRef } from "react"
import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { Transaction, AIUsageStats } from "@/api/types"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Bot, Send, Search, Plus, Check, X, Loader2, ChevronDown, Clock } from "lucide-react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { toast } from "sonner"
import { money } from "@/lib/format"

interface ChatMessage {
  role: "user" | "assistant"
  content: string
}

const QUICK_PROMPTS = [
  "分析当前组合的风险",
  "给出调仓建议",
  "帮我录入一笔买入交易",
  "科技板块最近怎么样？",
]

const ACTION_LABELS: Record<string, string> = { buy: "买入", sell: "卖出", dividend: "分红", reinvest: "再投资" }

const SESSIONS_KEY = "zfundpilot_chat_sessions"
const LEGACY_KEY = "zfundpilot_chat_messages"

type TxState = Record<number, { state: "added"; id: number } | { state: "discarded" }>

interface SessionMeta {
  id: string
  title: string
  messages: ChatMessage[]
  txStatus: TxState
  systemPrompt: string
  updatedAt: string
}

interface PersistedSessions {
  activeId: string
  activeMessages: ChatMessage[]
  activeTxStatus: TxState
  activeSystemPrompt: string
  archive: SessionMeta[]
}

function newId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8)
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n) + "…" : s
}

function deriveTitle(messages: ChatMessage[]): string {
  const first = messages.find((m) => m.role === "user")
  if (!first) return "新对话"
  return truncate(first.content.replace(/\s+/g, " ").trim(), 24)
}

function formatRelativeTime(iso: string): string {
  // 后端存的是 UTC（datetime('now')），格式 "YYYY-MM-DD HH:MM:SS"
  // 加 T 和 Z 标记为 UTC，new Date() 自动转为本地时区
  const t = new Date(iso.replace(" ", "T") + "Z").getTime()
  if (isNaN(t)) return ""
  const diff = Date.now() - t
  const min = Math.floor(diff / 60000)
  if (min < 1) return "刚刚"
  if (min < 60) return `${min} 分钟前`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr} 小时前`
  const day = Math.floor(hr / 24)
  if (day === 1) return "昨天"
  if (day < 30) return `${day} 天前`
  const d = new Date(iso)
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日`
}

function formatTokens(n: number): string {
  if (n < 1000) return String(n)
  if (n < 1000000) return (n / 1000).toFixed(n < 10000 ? 1 : 0) + "k"
  return (n / 1000000).toFixed(1) + "m"
}

function loadSessions(): PersistedSessions {
  const empty = (): PersistedSessions => ({ activeId: newId(), activeMessages: [], activeTxStatus: {}, activeSystemPrompt: "", archive: [] })
  try {
    const raw = localStorage.getItem(SESSIONS_KEY)
    if (raw) {
      const p = JSON.parse(raw)
      if (p && Array.isArray(p.archive)) {
        return {
          activeId: p.activeId || newId(),
          activeMessages: Array.isArray(p.activeMessages) ? p.activeMessages : [],
          activeTxStatus: p.activeTxStatus ?? {},
          activeSystemPrompt: p.activeSystemPrompt ?? "",
          archive: p.archive.map((s: SessionMeta) => ({ ...s, systemPrompt: s.systemPrompt ?? "" })),
        }
      }
    }
  } catch { /* corrupt */ }
  // 迁移旧的单对话键
  try {
    const legacy = localStorage.getItem(LEGACY_KEY)
    if (legacy) {
      const old = JSON.parse(legacy)
      if (old && Array.isArray(old.messages) && old.messages.length > 0) {
        try { localStorage.removeItem(LEGACY_KEY) } catch {}
        return { activeId: newId(), activeMessages: old.messages, activeTxStatus: old.txStatus ?? {}, activeSystemPrompt: "", archive: [] }
      }
    }
  } catch {}
  return empty()
}

interface ExtractedTx {
  fund_code: string
  action: string
  date: string
  after_three: boolean
  amount: number | null
  shares: number | null
  nav: number | null
  fee: number
  channel: string
  note: string
}

function extractToolCall(content: string): ExtractedTx | null {
  const match = content.match(/```json\s*([\s\S]*?)```/)
  if (!match) return null
  try {
    const p = JSON.parse(match[1])
    if (p && p.tool === "add_transaction") {
      return {
        fund_code: String(p.fund_code ?? ""),
        action: String(p.action ?? "buy"),
        date: String(p.date ?? ""),
        after_three: Boolean(p.after_three),
        amount: p.amount != null ? Number(p.amount) : null,
        shares: p.shares != null ? Number(p.shares) : null,
        nav: p.nav != null ? Number(p.nav) : null,
        fee: p.fee != null ? Number(p.fee) : 0,
        channel: String(p.channel ?? ""),
        note: String(p.note ?? ""),
      }
    }
  } catch { /* incomplete or malformed */ }
  return null
}

function stripJsonBlock(content: string): string {
  return content.replace(/```json\s*[\s\S]*?```\s*/g, "").trim()
}

export default function AIChat() {
  const [restored] = useState(loadSessions)
  const [archive, setArchive] = useState<SessionMeta[]>(() => restored.archive)
  const [activeId, setActiveId] = useState(() => restored.activeId)
  const [messages, setMessages] = useState<ChatMessage[]>(() => restored.activeMessages)
  const [input, setInput] = useState("")
  const [streaming, setStreaming] = useState(false)
  const [searching, setSearching] = useState(false)
  const { data: aiConfig } = useApi(() => api.getAIConfig(), [])
  const chatEndRef = useRef<HTMLDivElement>(null)
  const [txStatus, setTxStatus] = useState<TxState>(() => restored.activeTxStatus)
  const [systemPrompt, setSystemPrompt] = useState(() => restored.activeSystemPrompt ?? "")
  const [adding, setAdding] = useState<number | null>(null)
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const [lastUsage, setLastUsage] = useState<{ prompt: number; completion: number; total: number } | null>(null)
  const { data: usageStats, reload: reloadUsage } = useApi<AIUsageStats>(() => api.getAIUsage(), [])
  const [showUsage, setShowUsage] = useState(false)

  // 持久化：当前会话 + 归档列表，切页面/刷新可恢复（含上下文）
  useEffect(() => {
    try {
      localStorage.setItem(SESSIONS_KEY, JSON.stringify({
        activeId, activeMessages: messages, activeTxStatus: txStatus,
        activeSystemPrompt: systemPrompt, archive,
      } as PersistedSessions))
    } catch { /* 配额满静默降级 */ }
  }, [messages, txStatus, activeId, archive])

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, searching])

  const handleSend = async (text?: string) => {
    const content = (text ?? input).trim()
    if (!content || streaming) return

    const userMsg: ChatMessage = { role: "user", content }
    const newMessages = [...messages, userMsg]
    setMessages([...newMessages, { role: "assistant", content: "" }])
    setInput("")
    setStreaming(true)
    setSearching(false)

    const aiIndex = newMessages.length

    try {
      // 新对话首条消息时取一次系统提示（含持仓快照），整个对话复用
      let sysPrompt = systemPrompt
      if (!sysPrompt) {
        try {
          const res = await api.getSystemPrompt()
          sysPrompt = res.system_prompt
          setSystemPrompt(sysPrompt)
        } catch { /* 取失败则不发 system，后端兜底构建 */ }
      }
      const messagesToSend = [
        ...(sysPrompt ? [{ role: "system", content: sysPrompt }] : []),
        ...newMessages.map((m) => ({ role: m.role, content: m.content })),
      ]
      await api.streamChat(
        messagesToSend,
        (chunk) => {
          if (chunk.status === "searching") {
            setSearching(true)
          } else if (chunk.content) {
            setSearching(false)
            setMessages((prev) => {
              const updated = [...prev]
              updated[aiIndex] = { role: "assistant", content: updated[aiIndex].content + chunk.content }
              return updated
            })
          } else if (chunk.usage) {
            setLastUsage(chunk.usage)
          } else if (chunk.error) {
            setSearching(false)
            setMessages((prev) => {
              const updated = [...prev]
              updated[aiIndex] = { role: "assistant", content: `❌ ${chunk.error}` }
              return updated
            })
          }
        },
      )
    } catch (e) {
      setMessages((prev) => {
        const updated = [...prev]
        updated[aiIndex] = { role: "assistant", content: `❌ 请求失败: ${e}` }
        return updated
      })
    } finally {
      setStreaming(false)
      setSearching(false)
      reloadUsage()
    }
  }

  const handleConfirmTx = async (msgIndex: number, tx: ExtractedTx) => {
    if (!tx.fund_code || !tx.date) {
      toast.error("基金代码和日期不能为空")
      return
    }
    const baseNote = tx.note.trim()
    const note = (baseNote ? baseNote + (tx.after_three ? " | " : "") : "") + (tx.after_three ? "T+1确认" : "")
    const payload: Transaction = {
      fund_code: tx.fund_code,
      action: tx.action,
      date: tx.date,
      amount: tx.amount,
      shares: tx.shares,
      nav: tx.nav,
      fee: tx.fee,
      channel: tx.channel,
      note,
    }
    setAdding(msgIndex)
    try {
      const res = await api.addTransaction(payload)
      toast.success(`${ACTION_LABELS[tx.action] ?? "交易"} ${tx.fund_code} 已添加（#${res.id}）`)
      setTxStatus((prev) => ({ ...prev, [msgIndex]: { state: "added", id: res.id } }))
    } catch (e) {
      toast.error(`添加失败: ${e}`)
    } finally {
      setAdding(null)
    }
  }

  const handleDiscardTx = (msgIndex: number) => {
    setTxStatus((prev) => ({ ...prev, [msgIndex]: { state: "discarded" } }))
  }

  // 把当前会话归档（仅当有内容），返回新 archive
  const archiveCurrent = (): SessionMeta[] => {
    if (messages.length === 0) return archive
    const session: SessionMeta = {
      id: activeId,
      title: deriveTitle(messages),
      messages,
      txStatus,
      systemPrompt,
      updatedAt: new Date().toISOString(),
    }
    return [session, ...archive]
  }

  const handleNewChat = () => {
    setArchive(archiveCurrent())
    setActiveId(newId())
    setMessages([])
    setTxStatus({})
    setSystemPrompt("")
    setInput("")
    setDropdownOpen(false)
  }

  const handleSwitchChat = (id: string) => {
    const target = archive.find((s) => s.id === id)
    if (!target) return
    setArchive(archiveCurrent().filter((s) => s.id !== id))
    setActiveId(target.id)
    setMessages(target.messages)
    setTxStatus(target.txStatus)
    setSystemPrompt(target.systemPrompt)
    setInput("")
    setDropdownOpen(false)
  }

  const handleDeleteArchived = (id: string) => {
    setArchive((prev) => prev.filter((s) => s.id !== id))
  }

  const configured = aiConfig?.base_url && aiConfig?.model

  return (
    <div className="flex flex-col h-[62vh] md:h-[calc(100vh-8rem)]">
      <h1 className="text-xl md:text-2xl font-bold mb-4">AI 助手</h1>
      <Card className="flex flex-col flex-1 min-h-0">
        <CardHeader className="pb-3 flex-row items-center justify-between gap-2">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <Bot className="h-5 w-5 text-blue-500 shrink-0" />
              {archive.length > 0 ? (
                <div className="relative">
                  <button
                    type="button"
                    onClick={() => setDropdownOpen((o) => !o)}
                    className="flex items-center gap-1 text-base font-bold hover:text-blue-600 transition-colors"
                  >
                    <span className="truncate max-w-[140px] sm:max-w-[220px]">{deriveTitle(messages)}</span>
                    <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform ${dropdownOpen ? "rotate-180" : ""}`} />
                  </button>
                  {dropdownOpen && (
                    <>
                      <div className="fixed inset-0 z-40" onClick={() => setDropdownOpen(false)} />
                      <div className="absolute left-0 top-full mt-1 z-50 w-72 max-w-[80vw] rounded-lg border bg-white shadow-lg">
                        <div className="flex items-center gap-2 px-3 py-2 border-b">
                          <span className="h-2 w-2 rounded-full bg-blue-500 shrink-0" />
                          <span className="text-sm font-medium truncate flex-1">{deriveTitle(messages)}</span>
                          <span className="text-[11px] text-muted-foreground shrink-0">当前</span>
                        </div>
                        {archive.length === 0 ? (
                          <p className="px-3 py-3 text-center text-xs text-muted-foreground">暂无历史对话</p>
                        ) : (
                          <div className="max-h-64 overflow-y-auto py-1">
                            {archive.map((s) => (
                              <div
                                key={s.id}
                                className="group flex items-center gap-2 px-3 py-2 hover:bg-slate-50 cursor-pointer"
                                onClick={() => handleSwitchChat(s.id)}
                              >
                                <Clock className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                                <div className="flex-1 min-w-0">
                                  <p className="text-sm truncate">{s.title}</p>
                                  <p className="text-[11px] text-muted-foreground">{formatRelativeTime(s.updatedAt)}</p>
                                </div>
                                <button
                                  type="button"
                                  onClick={(e) => { e.stopPropagation(); handleDeleteArchived(s.id) }}
                                  className="opacity-0 group-hover:opacity-100 shrink-0 rounded p-1 text-muted-foreground hover:text-red-500 hover:bg-red-50 transition-colors"
                                  title="删除此对话"
                                >
                                  <X className="h-3.5 w-3.5" />
                                </button>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </>
                  )}
                </div>
              ) : (
                <span className="text-base font-bold truncate">{deriveTitle(messages)}</span>
              )}
            </div>
            <p className="text-sm text-muted-foreground mt-1">
              基于实时资讯 + 当前持仓数据，给出风险分析与调仓建议；也可描述交易让 AI 帮你录入
            </p>
          </div>
          <Button variant="outline" size="sm" className="h-7 shrink-0" onClick={handleNewChat} disabled={streaming} title="开始新对话">
            <Plus className="h-3.5 w-3.5 mr-1" /> 新对话
          </Button>
        </CardHeader>
        <CardContent className="flex flex-col flex-1 min-h-0 gap-3">
          {!configured ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              请先到「设置」页面配置 AI 模型 API
            </p>
          ) : (
            <>
              {/* 消息列表 */}
              <div className="flex-1 overflow-y-auto space-y-3 rounded-lg border bg-slate-50/50 p-4 min-h-0">
                {messages.length === 0 && (
                  <p className="py-6 text-center text-sm text-muted-foreground">
                    开始对话吧！AI 会先搜索最新市场资讯，再结合你的持仓给出建议。
                    <br />
                    描述一笔交易（如「昨天在支付宝买了1000元005827」），AI 会帮你生成记录待确认。
                  </p>
                )}
                {messages.map((msg, i) => {
                  const tx = msg.role === "assistant" ? extractToolCall(msg.content) : null
                  const display = msg.role === "assistant" ? stripJsonBlock(msg.content) : msg.content
                  const status = txStatus[i]
                  return (
                    <div key={i} className={msg.role === "user" ? "text-right" : "text-left"}>
                      <div
                        className={
                          msg.role === "user"
                            ? "inline-block max-w-[85%] rounded-lg bg-blue-600 px-3 py-2 text-sm text-white"
                            : "inline-block max-w-[85%] rounded-lg bg-white border px-3 py-2 text-sm"
                        }
                      >
                        {msg.role === "assistant" ? (
                          display ? (
                            <div className="prose prose-sm max-w-none prose-p:my-1 prose-ul:my-1 prose-ol:my-1 prose-li:my-0 prose-headings:mb-1 prose-headings:mt-2">
                              <ReactMarkdown remarkPlugins={[remarkGfm]}>{display}</ReactMarkdown>
                            </div>
                          ) : streaming && i === messages.length - 1 ? (
                            <span className="text-muted-foreground">正在思考...</span>
                          ) : null
                        ) : (
                          msg.content
                        )}
                      </div>
                      {tx && !streaming && (
                        <TxConfirmCard
                          tx={tx}
                          status={status}
                          adding={adding === i}
                          onConfirm={(finalTx) => handleConfirmTx(i, finalTx)}
                          onDiscard={() => handleDiscardTx(i)}
                        />
                      )}
                    </div>
                  )
                })}
                {searching && (
                  <div className="text-left">
                    <span className="inline-flex items-center gap-1.5 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-sm text-amber-700">
                      <Search className="h-3.5 w-3.5 animate-pulse" />
                      正在搜索最新资讯...
                    </span>
                  </div>
                )}
                <div ref={chatEndRef} />
              </div>

              {/* 快捷提示 */}
              <div className="flex flex-wrap gap-2 shrink-0">
                {QUICK_PROMPTS.map((prompt) => (
                  <button
                    key={prompt}
                    onClick={() => !streaming && handleSend(prompt)}
                    disabled={streaming}
                    className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs text-slate-600 transition-colors hover:border-blue-300 hover:bg-blue-50 hover:text-blue-600 disabled:opacity-50"
                  >
                    {prompt}
                  </button>
                ))}
              </div>

              {/* 输入区 */}
              <div className="flex gap-2 shrink-0">
                <Input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault()
                      handleSend()
                    }
                  }}
                  disabled={streaming}
                />
                <Button
                  onClick={() => handleSend()}
                  disabled={streaming || !input.trim()}
                  size="icon"
                  className="shrink-0"
                >
                  {streaming ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                </Button>
              </div>

              {/* token 用量状态栏 */}
              <div className="flex items-center justify-between shrink-0">
                <p className="text-[11px] text-muted-foreground/70">
                  {lastUsage
                    ? `本次 ${formatTokens(lastUsage.total)}（入 ${formatTokens(lastUsage.prompt)} / 出 ${formatTokens(lastUsage.completion)}）`
                    : "等待回复即可查看本次 token 消耗"}
                  {usageStats ? ` · 今日 ${formatTokens(usageStats.today)} · 累计 ${formatTokens(usageStats.total)}` : ""}
                </p>
                {usageStats && usageStats.recent.length > 0 && (
                  <button
                    type="button"
                    onClick={() => setShowUsage(true)}
                    className="text-[11px] text-muted-foreground/60 hover:text-blue-500 hover:underline transition-colors"
                  >
                    用量明细
                  </button>
                )}
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* 用量明细弹窗 */}
      {showUsage && usageStats && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setShowUsage(false)}>
          <div className="w-full max-w-md rounded-lg bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-bold">AI 用量明细</h3>
              <span className="text-xs text-muted-foreground">今日 {formatTokens(usageStats.today)} · 累计 {formatTokens(usageStats.total)}</span>
            </div>
            <div className="max-h-72 overflow-y-auto space-y-1">
              {usageStats.recent.map((r) => (
                <div key={r.id} className="flex items-center justify-between rounded-md bg-slate-50 px-3 py-2 text-xs">
                  <div className="flex items-center gap-2 min-w-0">
                    <Clock className="h-3 w-3 text-muted-foreground shrink-0" />
                    <span className="text-muted-foreground shrink-0">{formatRelativeTime(r.created_at)}</span>
                    <span className="truncate">{r.model || "—"}</span>
                  </div>
                  <span className="tabular-nums shrink-0 ml-2">
                    {formatTokens(r.total_tokens)}（入 {formatTokens(r.prompt_tokens)} / 出 {formatTokens(r.completion_tokens)}）
                    <span className="text-muted-foreground ml-1">· {r.turns} 轮</span>
                  </span>
                </div>
              ))}
            </div>
            <div className="mt-3 text-right">
              <Button variant="outline" size="sm" className="h-7" onClick={() => setShowUsage(false)}>
                关闭
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// 交易确认卡片
// ---------------------------------------------------------------------------
function TxConfirmCard({
  tx,
  status,
  adding,
  onConfirm,
  onDiscard,
}: {
  tx: ExtractedTx
  status?: { state: "added"; id: number } | { state: "discarded" }
  adding: boolean
  onConfirm: (tx: ExtractedTx) => void
  onDiscard: () => void
}) {
  const [editDate, setEditDate] = useState(tx.date)
  const [afterThree, setAfterThree] = useState(tx.after_three)

  useEffect(() => { setEditDate(tx.date); setAfterThree(tx.after_three) }, [tx.date, tx.after_three])

  if (status?.state === "added") {
    return (
      <div className="mt-2 inline-flex items-center gap-1.5 rounded-lg border border-green-200 bg-green-50 px-3 py-1.5 text-sm text-green-700">
        <Check className="h-3.5 w-3.5" /> 已添加交易 #{status.id}
      </div>
    )
  }
  if (status?.state === "discarded") {
    return (
      <div className="mt-2 inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 text-sm text-muted-foreground">
        <X className="h-3.5 w-3.5" /> 已丢弃
      </div>
    )
  }

  const finalTx: ExtractedTx = { ...tx, date: editDate, after_three: afterThree }
  const canConfirm = !!finalTx.fund_code && !!finalTx.date && !adding

  return (
    <div className="mt-2 inline-block text-left w-full max-w-[85%] rounded-lg border border-blue-200 bg-blue-50/40 p-3">
      <div className="flex items-center gap-2 mb-2.5">
        <Plus className="h-4 w-4 text-blue-500" />
        <span className="text-sm font-medium">待确认交易</span>
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
        <div className="flex items-center gap-1.5">
          <span className="text-muted-foreground">操作</span>
          <Badge variant={tx.action === "buy" ? "success" : tx.action === "sell" ? "destructive" : "outline"}>
            {ACTION_LABELS[tx.action] ?? tx.action}
          </Badge>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-muted-foreground">代码</span>
          <span className="font-mono text-xs">{tx.fund_code || "—"}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-muted-foreground">日期</span>
          {tx.date ? (
            <span>{tx.date}</span>
          ) : (
            <Input
              type="date"
              value={editDate}
              onChange={(e) => setEditDate(e.target.value)}
              className="h-7 w-36 text-xs"
            />
          )}
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-muted-foreground">渠道</span>
          <span>{tx.channel || "—"}</span>
        </div>
        <div className="col-span-2 flex items-center gap-2">
          <span className="text-muted-foreground">下单时间</span>
          <button
            type="button"
            onClick={() => setAfterThree(!afterThree)}
            className={`rounded-full border px-2.5 py-0.5 text-xs transition-colors ${afterThree ? "border-amber-300 bg-amber-50 text-amber-700" : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50"}`}
          >
            {afterThree ? "15:00 后（T+1 确认）" : "15:00 前（当日确认）"}
          </button>
        </div>
        {tx.amount != null && (
          <div className="flex items-center gap-1.5">
            <span className="text-muted-foreground">金额</span>
            <span className="tabular-nums">{money(tx.amount)}</span>
          </div>
        )}
        {tx.shares != null && (
          <div className="flex items-center gap-1.5">
            <span className="text-muted-foreground">份额</span>
            <span className="tabular-nums">{tx.shares.toFixed(2)}</span>
          </div>
        )}
        {tx.nav != null && (
          <div className="flex items-center gap-1.5">
            <span className="text-muted-foreground">净值</span>
            <span className="tabular-nums">{tx.nav.toFixed(4)}</span>
          </div>
        )}
        {tx.fee ? (
          <div className="flex items-center gap-1.5">
            <span className="text-muted-foreground">手续费</span>
            <span className="tabular-nums">{money(tx.fee)}</span>
          </div>
        ) : null}
        {tx.note && (
          <div className="col-span-2 flex items-center gap-1.5">
            <span className="text-muted-foreground">备注</span>
            <span>{tx.note}</span>
          </div>
        )}
      </div>
      <div className="flex gap-2 mt-3">
        <Button size="sm" className="h-7" onClick={() => onConfirm(finalTx)} disabled={!canConfirm}>
          {adding ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" /> : <Check className="h-3.5 w-3.5 mr-1" />}
          {adding ? "添加中..." : "确认添加"}
        </Button>
        <Button size="sm" variant="outline" className="h-7" onClick={onDiscard} disabled={adding}>
          <X className="h-3.5 w-3.5 mr-1" /> 丢弃
        </Button>
      </div>
    </div>
  )
}
