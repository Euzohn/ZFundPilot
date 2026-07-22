import { useState, useEffect, useRef, useCallback } from "react"
import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { Transaction, AIUsageStats, CalcFeeResponse } from "@/api/types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import FeeBreakdownCard from "@/components/FeeBreakdownCard"
import { ChevronDown, ChevronRight, Eye, EyeOff, ShieldAlert, Lightbulb, PlusCircle, Newspaper } from "lucide-react"
import { Bot, Send, Search, Plus, Check, X, Loader2, Clock, Pencil } from "lucide-react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { toast } from "sonner"
import { money, formatRelativeTime, formatTokens } from "@/lib/format"
import { ACTION_LABELS } from "@/lib/actionLabels"
import LogoTyping from "@/components/LogoTyping"
import EmptyState from "@/components/EmptyState"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog"

interface ChatMessage {
  role: "user" | "assistant"
  content: string
}

const QUICK_PROMPTS = [
  { text: "分析当前组合的风险", icon: ShieldAlert },
  { text: "给出调仓建议", icon: Lightbulb },
  { text: "帮我录入一笔买入交易", icon: PlusCircle },
  { text: "科技板块最近怎么样？", icon: Newspaper },
]

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
  activeTitle: string
  activeMessages: ChatMessage[]
  activeTxStatus: TxState
  activeSystemPrompt: string
  includeContext: boolean
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

function generateTimeTitle(): string {
  const now = new Date()
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}`
}

function loadSessions(): PersistedSessions {
  const empty = (): PersistedSessions => ({ activeId: newId(), activeTitle: "", activeMessages: [], activeTxStatus: {}, activeSystemPrompt: "", includeContext: true, archive: [] })
  try {
    const raw = localStorage.getItem(SESSIONS_KEY)
    if (raw) {
      const p = JSON.parse(raw)
      if (p && Array.isArray(p.archive)) {
        return {
          activeId: p.activeId || newId(),
          activeTitle: p.activeTitle || "",
          activeMessages: Array.isArray(p.activeMessages) ? p.activeMessages : [],
          activeTxStatus: p.activeTxStatus ?? {},
          activeSystemPrompt: p.activeSystemPrompt ?? "",
          includeContext: p.includeContext !== false,
          archive: p.archive.map((s: SessionMeta) => ({ ...s, systemPrompt: s.systemPrompt ?? "" })),
        }
      }
    }
  } catch { /* corrupt */ }
  try {
    const legacy = localStorage.getItem(LEGACY_KEY)
    if (legacy) {
      const old = JSON.parse(legacy)
      if (old && Array.isArray(old.messages) && old.messages.length > 0) {
        try { localStorage.removeItem(LEGACY_KEY) } catch {}
        return { activeId: newId(), activeTitle: "", activeMessages: old.messages, activeTxStatus: old.txStatus ?? {}, activeSystemPrompt: "", includeContext: true, archive: [] }
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
  const [currentTitle, setCurrentTitle] = useState(() => restored.activeTitle || deriveTitle(restored.activeMessages))
  const [messages, setMessages] = useState<ChatMessage[]>(() => restored.activeMessages)
  const [input, setInput] = useState("")
  const [streaming, setStreaming] = useState(false)
  const [searching, setSearching] = useState(false)
  const { data: aiConfig } = useApi(() => api.getAIConfig(), [])
  const chatEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const [txStatus, setTxStatus] = useState<TxState>(() => restored.activeTxStatus)
  const [systemPrompt, setSystemPrompt] = useState(() => restored.activeSystemPrompt ?? "")
  const [includeContext, setIncludeContext] = useState(() => restored.includeContext)
  const [showSysPrompt, setShowSysPrompt] = useState(false)
  const [adding, setAdding] = useState<number | null>(null)
  const [dropdownOpen, setDropdownOpen] = useState(false)
  const [lastUsage, setLastUsage] = useState<{ prompt: number; completion: number; total: number } | null>(null)
  const { data: usageStats, reload: reloadUsage } = useApi<AIUsageStats>(() => api.getAIUsage(), [])
  const [showUsage, setShowUsage] = useState(false)
  const [editingTitle, setEditingTitle] = useState(false)
  const [editingArchiveId, setEditingArchiveId] = useState<string | null>(null)
  const [titleInput, setTitleInput] = useState("")

  useEffect(() => {
    try {
      localStorage.setItem(SESSIONS_KEY, JSON.stringify({
        activeId, activeTitle: currentTitle, activeMessages: messages, activeTxStatus: txStatus,
        activeSystemPrompt: systemPrompt, includeContext, archive,
      } as PersistedSessions))
    } catch { /* 配额满静默降级 */ }
  }, [messages, txStatus, activeId, archive, currentTitle, systemPrompt, includeContext])

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, searching])

  const autoResize = useCallback(() => {
    const ta = textareaRef.current
    if (!ta) return
    ta.style.height = "auto"
    ta.style.height = Math.min(ta.scrollHeight, 120) + "px"
  }, [])

  useEffect(() => { autoResize() }, [input, autoResize])

  useEffect(() => {
    api.getSystemPrompt(includeContext).then((res) => {
      setSystemPrompt(res.system_prompt)
    }).catch(() => {})
  }, [includeContext])

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
      let sysPrompt = systemPrompt
      if (!sysPrompt) {
        try {
          const res = await api.getSystemPrompt(includeContext)
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

  const archiveCurrent = (): SessionMeta[] => {
    if (messages.length === 0) return archive
    const session: SessionMeta = {
      id: activeId,
      title: currentTitle || deriveTitle(messages),
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
    setCurrentTitle(generateTimeTitle())
    setMessages([])
    setTxStatus({})
    setSystemPrompt("")
    setInput("")
    setDropdownOpen(false)
    setEditingTitle(false)
  }

  const handleSwitchChat = (id: string) => {
    const target = archive.find((s) => s.id === id)
    if (!target) return
    setArchive(archiveCurrent().filter((s) => s.id !== id))
    setActiveId(target.id)
    setCurrentTitle(target.title)
    setMessages(target.messages)
    setTxStatus(target.txStatus)
    setSystemPrompt(target.systemPrompt)
    setInput("")
    setDropdownOpen(false)
    setEditingTitle(false)
  }

  const handleDeleteArchived = (id: string) => {
    setArchive((prev) => prev.filter((s) => s.id !== id))
  }

  const handleRenameArchived = (id: string, newTitle: string) => {
    const title = newTitle.trim()
    if (title) {
      setArchive((prev) => prev.map((s) => s.id === id ? { ...s, title } : s))
    }
    setEditingArchiveId(null)
  }

  const startEditTitle = () => {
    setTitleInput(currentTitle)
    setEditingTitle(true)
  }

  const saveTitle = () => {
    const title = titleInput.trim()
    if (title) setCurrentTitle(title)
    setEditingTitle(false)
  }

  const configured = aiConfig?.base_url && aiConfig?.model

  return (
    <div className="flex flex-col h-[calc(100dvh-9rem)] md:h-[calc(100dvh-8rem)] max-w-4xl mx-auto" style={{ paddingBottom: "env(safe-area-inset-bottom, 0px)" }}>
      {/* Header */}
      <div className="flex items-center justify-between gap-2 border-b pb-2 md:pb-3">
        <div className="flex items-center gap-2 min-w-0">
          <Bot className="h-5 w-5 text-primary shrink-0" />
          {editingTitle ? (
            <Input
              value={titleInput}
              onChange={(e) => setTitleInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.nativeEvent.isComposing) saveTitle()
                if (e.key === "Escape") setEditingTitle(false)
              }}
              onBlur={saveTitle}
              autoFocus
              className="h-7 text-base font-bold max-w-[200px] sm:max-w-[280px]"
            />
          ) : archive.length > 0 ? (
            <Popover open={dropdownOpen} onOpenChange={setDropdownOpen}>
              <div className="flex items-center gap-1">
                <PopoverTrigger asChild>
                  <button
                    type="button"
                    className="flex items-center gap-1 text-base font-bold hover:text-primary transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]"
                  >
                    <span className="truncate max-w-[100px] sm:max-w-[180px]">{currentTitle}</span>
                    <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform ${dropdownOpen ? "rotate-180" : ""}`} />
                  </button>
                </PopoverTrigger>
                <button
                  type="button"
                  onClick={startEditTitle}
                  className="shrink-0 rounded p-0.5 text-muted-foreground hover:text-primary transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]"
                  title="重命名"
                >
                  <Pencil className="h-3.5 w-3.5" />
                </button>
              </div>
              <PopoverContent className="w-72 max-w-[80vw]" align="start">
                <div className="flex items-center gap-2 px-3 py-2 border-b">
                  <span className="text-sm font-medium truncate flex-1">{currentTitle}</span>
                  <span className="text-[11px] text-muted-foreground shrink-0">当前</span>
                </div>
                {archive.length === 0 ? (
                  <EmptyState title="暂无历史对话" size="sm" />
                ) : (
                  <div className="max-h-64 overflow-y-auto py-1">
                    {archive.map((s) => (
                      <div
                        key={s.id}
                        className="group flex items-center gap-2 px-3 py-2 hover:bg-muted/50 cursor-pointer"
                        onClick={() => handleSwitchChat(s.id)}
                      >
                        <Clock className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                        <div className="flex-1 min-w-0">
                          {editingArchiveId === s.id ? (
                            <Input
                              value={titleInput}
                              onChange={(e) => setTitleInput(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === "Enter" && !e.nativeEvent.isComposing) handleRenameArchived(s.id, titleInput)
                                if (e.key === "Escape") setEditingArchiveId(null)
                              }}
                              onBlur={() => handleRenameArchived(s.id, titleInput)}
                              onClick={(e) => e.stopPropagation()}
                              autoFocus
                              className="h-6 text-sm"
                            />
                          ) : (
                            <>
                              <p className="text-sm truncate">{s.title}</p>
                              <p className="text-[11px] text-muted-foreground">{formatRelativeTime(s.updatedAt)}</p>
                            </>
                          )}
                        </div>
                        {editingArchiveId !== s.id && (
                          <>
                            <button
                              type="button"
                              onClick={(e) => { e.stopPropagation(); setTitleInput(s.title); setEditingArchiveId(s.id) }}
                              className="opacity-0 group-hover:opacity-100 shrink-0 rounded p-1 text-muted-foreground hover:text-primary hover:bg-primary/5 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]"
                              title="重命名"
                            >
                              <Pencil className="h-3 w-3" />
                            </button>
                            <button
                              type="button"
                              onClick={(e) => { e.stopPropagation(); handleDeleteArchived(s.id) }}
                              className="opacity-0 group-hover:opacity-100 shrink-0 rounded p-1 text-muted-foreground hover:text-destructive hover:bg-destructive/5 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]"
                              title="删除此对话"
                            >
                              <X className="h-3.5 w-3.5" />
                            </button>
                          </>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </PopoverContent>
            </Popover>
          ) : (
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={startEditTitle}
                className="text-base font-bold truncate hover:text-primary transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]"
              >
                {currentTitle}
              </button>
              <button
                type="button"
                onClick={startEditTitle}
                className="shrink-0 rounded p-0.5 text-muted-foreground hover:text-primary transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]"
                title="重命名"
              >
                <Pencil className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            type="button"
            onClick={() => setIncludeContext(!includeContext)}
            disabled={streaming}
            className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98] ${includeContext ? "border-primary/30 bg-primary/5 text-primary" : "border-border bg-card text-muted-foreground"}`}
            title={includeContext ? "当前携带持仓明细" : "不携带持仓明细"}
          >
            {includeContext ? <Eye className="h-3 w-3" /> : <EyeOff className="h-3 w-3" />}
            <span>持仓明细</span>
          </button>
          <Button variant="outline" size="sm" className="h-7 shrink-0" onClick={handleNewChat} disabled={streaming} title="开始新对话">
            <Plus className="h-3.5 w-3.5 mr-1" /> 新对话
          </Button>
        </div>
      </div>

      {/* Chat body */}
      {configured ? (
        <div className="flex flex-col flex-1 min-h-0 gap-2 md:gap-3 pt-2 md:pt-3">
          {/* 系统提示词折叠面板 */}
          {systemPrompt && (
            <div className="shrink-0 rounded-xl border bg-muted/30">
              <button
                type="button"
                onClick={() => setShowSysPrompt(!showSysPrompt)}
                className="flex w-full items-center gap-1.5 px-3 py-1.5 text-[11px] text-muted-foreground hover:text-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]"
              >
                {showSysPrompt ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
                <span>系统提示词</span>
                <span className="text-[10px] text-muted-foreground/50">
                  ({includeContext ? "含持仓明细" : "不含持仓明细"} · {systemPrompt.length} 字符)
                </span>
              </button>
              {showSysPrompt && (
                <pre className="max-h-48 overflow-y-auto px-3 pb-2 text-[11px] leading-relaxed text-muted-foreground whitespace-pre-wrap font-mono">
                  {systemPrompt}
                </pre>
              )}
            </div>
          )}

          {/* 消息列表 */}
          <div className="flex-1 overflow-y-auto space-y-4 min-h-0">
            {messages.length === 0 && (
              <div className="flex flex-col items-center justify-center h-full gap-4 text-center">
                <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10">
                  <Bot className="h-8 w-8 text-primary" />
                </div>
                <div className="space-y-1">
                  <p className="text-base font-semibold">AI 投资助手</p>
                  <p className="text-sm text-muted-foreground max-w-sm">
                    搜索实时市场资讯，结合你的持仓给出风险分析与调仓建议。也可描述交易让 AI 帮你录入。
                  </p>
                </div>
                <div className="grid grid-cols-2 gap-2 w-full max-w-md mt-2">
                  {QUICK_PROMPTS.map(({ text, icon: Icon }) => (
                    <button
                      key={text}
                      onClick={() => !streaming && handleSend(text)}
                      disabled={streaming}
                      className="flex items-center gap-2 rounded-xl border border-border bg-card px-3 py-2.5 text-left text-xs text-foreground transition-colors hover:border-primary/30 hover:bg-primary/5 disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]"
                    >
                      <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
                      <span className="leading-tight">{text}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((msg, i) => {
              const tx = msg.role === "assistant" ? extractToolCall(msg.content) : null
              const display = msg.role === "assistant" ? stripJsonBlock(msg.content) : msg.content
              const status = txStatus[i]
              return (
                <div key={i} className={msg.role === "user" ? "flex justify-end" : "flex justify-start gap-2.5"}>
                  {msg.role === "assistant" && (
                    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-primary/10 mt-0.5">
                      <Bot className="h-4 w-4 text-primary" />
                    </div>
                  )}
                  <div className={msg.role === "user" ? "max-w-[80%]" : "max-w-[80%] flex-1"}>
                    {msg.role === "user" ? (
                      <div className="inline-block rounded-xl bg-primary px-3.5 py-2 text-sm text-primary-foreground">
                        {msg.content}
                      </div>
                    ) : display ? (
                      <div className="prose prose-sm max-w-none prose-p:my-1 prose-ul:my-1 prose-ol:my-1 prose-li:my-0 prose-headings:mb-1 prose-headings:mt-2">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{display}</ReactMarkdown>
                      </div>
                    ) : streaming && i === messages.length - 1 ? (
                      <span className="inline-flex items-center gap-2 text-muted-foreground text-sm">
                        <LogoTyping className="h-5 w-5" />
                        思考中...
                      </span>
                    ) : null}
                  </div>
                  {tx && !streaming && (
                    <div className="hidden" />
                  )}
                </div>
              )
            })}
            {messages.map((msg, i) => {
              const tx = msg.role === "assistant" ? extractToolCall(msg.content) : null
              const status = txStatus[i]
              return tx && !streaming ? (
                <div key={`tx-${i}`} className="flex justify-start gap-2.5">
                  <div className="w-7 shrink-0" />
                  <div className="max-w-[80%] flex-1">
                    <TxConfirmCard
                      tx={tx}
                      status={status}
                      adding={adding === i}
                      onConfirm={(finalTx) => handleConfirmTx(i, finalTx)}
                      onDiscard={() => handleDiscardTx(i)}
                    />
                  </div>
                </div>
              ) : null
            })}
            {searching && (
              <div className="flex justify-start gap-2.5">
                <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-muted mt-0.5">
                  <Search className="h-3.5 w-3.5 text-muted-foreground animate-pulse" />
                </div>
                <span className="inline-flex items-center rounded-lg bg-muted px-3 py-2 text-sm text-muted-foreground">
                  搜索最新资讯中...
                </span>
              </div>
            )}
            <div ref={chatEndRef} />
          </div>

          {/* 输入区 */}
          <div className="shrink-0">
            <div className="flex items-end gap-2 rounded-xl border border-border bg-card px-3 py-2 shadow-sm focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-1 transition-shadow">
              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault()
                    handleSend()
                  }
                }}
                disabled={streaming}
                rows={1}
                placeholder="输入消息，Enter 发送，Shift+Enter 换行"
                className="flex-1 resize-none bg-transparent text-sm leading-relaxed outline-none placeholder:text-muted-foreground/60 disabled:opacity-50"
                style={{ maxHeight: "120px" }}
              />
              <Button
                onClick={() => handleSend()}
                disabled={streaming || !input.trim()}
                size="icon"
                className="shrink-0 h-8 w-8"
              >
                {streaming ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              </Button>
            </div>
            {/* token 用量 */}
            <div className="flex items-center justify-between mt-1 px-1">
              <p className="text-[10px] text-muted-foreground/60">
                {lastUsage
                  ? `本次 ${formatTokens(lastUsage.total)} (入 ${formatTokens(lastUsage.prompt)} / 出 ${formatTokens(lastUsage.completion)})`
                  : "回复后显示 token 消耗"}
                {usageStats ? ` · 今日 ${formatTokens(usageStats.today)} · 累计 ${formatTokens(usageStats.total)}` : ""}
              </p>
              {usageStats && usageStats.recent.length > 0 && (
                <button
                  type="button"
                  onClick={() => setShowUsage(true)}
                  className="text-[10px] text-muted-foreground/50 hover:text-primary transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]"
                >
                  用量明细
                </button>
              )}
            </div>
          </div>
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center flex-1 gap-3 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-muted">
            <Bot className="h-8 w-8 text-muted-foreground" />
          </div>
          <p className="text-sm text-muted-foreground">请先到「设置」页面配置 AI 模型 API</p>
        </div>
      )}

      {/* 用量明细弹窗 */}
      <Dialog open={showUsage && !!usageStats} onOpenChange={(open) => !open && setShowUsage(false)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>AI 用量明细</DialogTitle>
            <DialogDescription>今日 {formatTokens(usageStats?.today ?? 0)} · 累计 {formatTokens(usageStats?.total ?? 0)}</DialogDescription>
          </DialogHeader>
          <div className="max-h-72 overflow-y-auto space-y-1">
            {usageStats?.recent.map((r) => (
              <div key={r.id} className="flex items-center justify-between rounded-lg bg-muted/50 px-3 py-2 text-xs">
                <div className="flex items-center gap-2 min-w-0">
                  <Clock className="h-3 w-3 text-muted-foreground shrink-0" />
                  <span className="text-muted-foreground shrink-0">{formatRelativeTime(r.created_at)}</span>
                  <span className="truncate">{r.model || "-"}</span>
                </div>
                <span className="tabular-nums shrink-0 ml-2">
                  {formatTokens(r.total_tokens)}(入 {formatTokens(r.prompt_tokens)} / 出 {formatTokens(r.completion_tokens)})
                  <span className="text-muted-foreground ml-1">· {r.turns} 轮</span>
                </span>
              </div>
            ))}
          </div>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setShowUsage(false)}>
              关闭
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

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
  const [editFee, setEditFee] = useState(() => tx.fee ? String(tx.fee) : "")
  const [feeCalcResult, setFeeCalcResult] = useState<CalcFeeResponse | null>(null)
  const [feeCalcLoading, setFeeCalcLoading] = useState(false)
  const [estimatedAmount, setEstimatedAmount] = useState<number | null>(null)
  const [estimatedNav, setEstimatedNav] = useState<number | null>(null)

  useEffect(() => {
    setEditDate(tx.date)
    setAfterThree(tx.after_three)
  }, [tx.date, tx.after_three])

  useEffect(() => {
    if (!tx.fund_code) return
    const amt = tx.amount ?? 0
    const sh = tx.shares ?? 0
    const dt = tx.date
    if (tx.action === "buy" && amt > 0) {
      setFeeCalcLoading(true)
      api.calcFundFee(tx.fund_code, { action: "buy", amount: amt })
        .then((res) => {
          setFeeCalcResult(res)
          if (!tx.fee && res.fee > 0) {
            setEditFee(res.fee.toFixed(2))
          }
        })
        .catch(() => {})
        .finally(() => setFeeCalcLoading(false))
    } else if (tx.action === "sell" && sh > 0 && dt) {
      setFeeCalcLoading(true)
      api.calcFundFee(tx.fund_code, { action: "sell", shares: sh, date: dt })
        .then((res) => {
          setFeeCalcResult(res)
          if (!tx.fee && res.fee > 0) {
            setEditFee(res.fee.toFixed(2))
          }
          if (res.nav) setEstimatedNav(res.nav)
          if (res.amount > 0) setEstimatedAmount(res.amount)
        })
        .catch(() => {})
        .finally(() => setFeeCalcLoading(false))
    }
  }, [tx.fund_code, tx.action, tx.amount, tx.shares, tx.date])

  if (status?.state === "added") {
    return (
      <div className="mt-2 inline-flex items-center gap-1.5 rounded-xl border border-gain-200 bg-gain-50 px-3 py-1.5 text-sm text-gain-700">
        <Check className="h-3.5 w-3.5" /> 已添加交易 #{status.id}
      </div>
    )
  }
  if (status?.state === "discarded") {
    return (
      <div className="mt-2 inline-flex items-center gap-1.5 rounded-xl border bg-muted px-3 py-1.5 text-sm text-muted-foreground">
        <X className="h-3.5 w-3.5" /> 已丢弃
      </div>
    )
  }

  const finalTx: ExtractedTx = {
    ...tx, date: editDate, after_three: afterThree,
    fee: parseFloat(editFee) || 0,
    amount: tx.amount ?? estimatedAmount ?? null,
    nav: tx.nav ?? estimatedNav ?? null,
  }
  const canConfirm = !!finalTx.fund_code && !!finalTx.date && !adding

  return (
    <div className="mt-2 inline-block text-left w-full rounded-xl border border-primary/20 bg-primary/5 p-3">
      <div className="flex items-center gap-2 mb-2.5">
        <Plus className="h-4 w-4 text-primary" />
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
          <span className="font-mono text-xs">{tx.fund_code || "-"}</span>
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
          <span>{tx.channel || "-"}</span>
        </div>
        <div className="col-span-2 flex items-center gap-2">
          <span className="text-muted-foreground">下单时间</span>
          <button
            type="button"
            onClick={() => setAfterThree(!afterThree)}
            className={`rounded-full border px-2.5 py-0.5 text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98] ${afterThree ? "border-accent/30 bg-accent/10 text-accent" : "border-border bg-card text-muted-foreground"}`}
          >
            {afterThree ? "15:00 后（T+1 确认）" : "15:00 前（当日确认）"}
          </button>
        </div>
        {finalTx.amount != null && (
          <div className="flex items-center gap-1.5">
            <span className="text-muted-foreground">金额</span>
            <span className="tabular-nums">{money(finalTx.amount)}</span>
            {estimatedAmount != null && tx.action === "sell" && <span className="text-[10px] text-muted-foreground">(估算)</span>}
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
        <div className="flex items-center gap-1.5">
          <span className="text-muted-foreground">手续费</span>
          <Input
            type="number"
            step="0.01"
            min="0"
            value={editFee}
            onChange={(e) => setEditFee(e.target.value)}
            className="h-7 w-24 text-xs tabular-nums"
            placeholder="0"
          />
          {feeCalcLoading && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />}
        </div>
      </div>
      {feeCalcResult && (
        <div className="mt-1.5">
          <FeeBreakdownCard result={feeCalcResult} action={tx.action === "sell" ? "sell" : "buy"} />
        </div>
      )}
      {tx.note && (
        <div className="mt-1.5 flex items-center gap-1.5 text-sm">
          <span className="text-muted-foreground">备注</span>
          <span>{tx.note}</span>
        </div>
      )}
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
