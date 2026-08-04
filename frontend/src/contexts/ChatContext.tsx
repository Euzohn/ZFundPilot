import { useState, useEffect, useCallback, createContext, useContext, type ReactNode } from "react"
import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { Transaction, AIUsageStats } from "@/api/types"
import { useLang } from "@/i18n/LanguageContext"
import { toast } from "sonner"

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
export interface ChatMessage {
  role: "user" | "assistant"
  content: string
}

export type TxState = Record<number, { state: "added"; id: number } | { state: "discarded" }>

export interface SessionMeta {
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

export interface ExtractedTx {
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

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const SESSIONS_KEY = "zfundpilot_chat_sessions"
const LEGACY_KEY = "zfundpilot_chat_messages"

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function newId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8)
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n) + "…" : s
}

function deriveTitle(messages: ChatMessage[], fallback = ""): string {
  const first = messages.find((m) => m.role === "user")
  if (!first) return fallback
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

export function extractToolCall(content: string): ExtractedTx | null {
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

export function stripJsonBlock(content: string): string {
  return content.replace(/```json\s*[\s\S]*?```\s*/g, "").trim()
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------
interface ChatContextValue {
  // State
  messages: ChatMessage[]
  streaming: boolean
  searching: boolean
  activeId: string
  currentTitle: string
  archive: SessionMeta[]
  txStatus: TxState
  systemPrompt: string
  includeContext: boolean
  lastUsage: { prompt: number; completion: number; total: number } | null
  usageStats: AIUsageStats | null
  // Actions
  handleSend: (text?: string) => Promise<void>
  handleNewChat: () => void
  handleSwitchChat: (id: string) => void
  handleDeleteArchived: (id: string) => void
  handleRenameArchived: (id: string, newTitle: string) => void
  handleConfirmTx: (msgIndex: number, tx: ExtractedTx) => Promise<void>
  handleDiscardTx: (msgIndex: number) => void
  setIncludeContext: (v: boolean) => void
  setCurrentTitle: (title: string) => void
  reloadUsage: () => void
}

const ChatContext = createContext<ChatContextValue | null>(null)

export function ChatProvider({ children }: { children: ReactNode }) {
  const { t } = useLang()
  const [restored] = useState(loadSessions)
  const [archive, setArchive] = useState<SessionMeta[]>(() => restored.archive)
  const [activeId, setActiveId] = useState(() => restored.activeId)
  const [currentTitle, setCurrentTitle] = useState(() => restored.activeTitle || deriveTitle(restored.activeMessages, t.aiChat.newChat))
  const [messages, setMessages] = useState<ChatMessage[]>(() => restored.activeMessages)
  const [streaming, setStreaming] = useState(false)
  const [searching, setSearching] = useState(false)
  const [txStatus, setTxStatus] = useState<TxState>(() => restored.activeTxStatus)
  const [systemPrompt, setSystemPrompt] = useState(() => restored.activeSystemPrompt ?? "")
  const [includeContext, setIncludeContext] = useState(() => restored.includeContext)
  const [lastUsage, setLastUsage] = useState<{ prompt: number; completion: number; total: number } | null>(null)
  const { data: usageStats, reload: reloadUsage } = useApi<AIUsageStats>(() => api.getAIUsage(), [])

  // localStorage persistence
  useEffect(() => {
    try {
      localStorage.setItem(SESSIONS_KEY, JSON.stringify({
        activeId, activeTitle: currentTitle, activeMessages: messages, activeTxStatus: txStatus,
        activeSystemPrompt: systemPrompt, includeContext, archive,
      } as PersistedSessions))
    } catch { /* 配额满静默降级 */ }
  }, [messages, txStatus, activeId, archive, currentTitle, systemPrompt, includeContext])

  // System prompt fetch
  useEffect(() => {
    api.getSystemPrompt(includeContext).then((res) => {
      setSystemPrompt(res.system_prompt)
    }).catch(() => {})
  }, [includeContext])

  const handleSend = useCallback(async (text?: string) => {
    const content = (text ?? "").trim()
    if (!content || streaming) return

    const userMsg: ChatMessage = { role: "user", content }
    const newMessages = [...messages, userMsg]
    setMessages([...newMessages, { role: "assistant", content: "" }])
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
        updated[aiIndex] = { role: "assistant", content: `❌ ${t.aiChat.requestFailed}: ${e}` }
        return updated
      })
    } finally {
      setStreaming(false)
      setSearching(false)
      reloadUsage()
    }
  }, [messages, streaming, systemPrompt, includeContext, t.aiChat.requestFailed, reloadUsage])

  const handleConfirmTx = useCallback(async (msgIndex: number, tx: ExtractedTx) => {
    if (!tx.fund_code || !tx.date) {
      toast.error(t.aiChat.fundCodeDateRequired)
      return
    }
    const baseNote = tx.note.trim()
    const note = (baseNote ? baseNote + (tx.after_three ? " | " : "") : "") + (tx.after_three ? t.transactions.t1Confirm : "")
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
    try {
      const res = await api.addTransaction(payload)
      toast.success(t.aiChat.txSuccess.replace("{action}", t.actionLabels[tx.action as keyof typeof t.actionLabels] ?? tx.action).replace("{code}", tx.fund_code).replace("{id}", String(res.id)))
      setTxStatus((prev) => ({ ...prev, [msgIndex]: { state: "added", id: res.id } }))
    } catch (e) {
      toast.error(`${t.aiChat.addFailed}: ${e}`)
    }
  }, [t])

  const handleDiscardTx = useCallback((msgIndex: number) => {
    setTxStatus((prev) => ({ ...prev, [msgIndex]: { state: "discarded" } }))
  }, [])

  const archiveCurrent = useCallback((): SessionMeta[] => {
    if (messages.length === 0) return archive
    const session: SessionMeta = {
      id: activeId,
      title: currentTitle || deriveTitle(messages, t.aiChat.newChat),
      messages,
      txStatus,
      systemPrompt,
      updatedAt: new Date().toISOString(),
    }
    return [session, ...archive]
  }, [messages, activeId, currentTitle, txStatus, systemPrompt, archive, t.aiChat.newChat])

  const handleNewChat = useCallback(() => {
    setArchive(archiveCurrent())
    setActiveId(newId())
    setCurrentTitle(generateTimeTitle())
    setMessages([])
    setTxStatus({})
    setSystemPrompt("")
  }, [archiveCurrent])

  const handleSwitchChat = useCallback((id: string) => {
    const target = archive.find((s) => s.id === id)
    if (!target) return
    setArchive(archiveCurrent().filter((s) => s.id !== id))
    setActiveId(target.id)
    setCurrentTitle(target.title)
    setMessages(target.messages)
    setTxStatus(target.txStatus)
    setSystemPrompt(target.systemPrompt)
  }, [archive, archiveCurrent])

  const handleDeleteArchived = useCallback((id: string) => {
    setArchive((prev) => prev.filter((s) => s.id !== id))
  }, [])

  const handleRenameArchived = useCallback((id: string, newTitle: string) => {
    const title = newTitle.trim()
    if (title) {
      setArchive((prev) => prev.map((s) => s.id === id ? { ...s, title } : s))
    }
  }, [])

  const value: ChatContextValue = {
    messages,
    streaming,
    searching,
    activeId,
    currentTitle,
    archive,
    txStatus,
    systemPrompt,
    includeContext,
    lastUsage,
    usageStats,
    handleSend,
    handleNewChat,
    handleSwitchChat,
    handleDeleteArchived,
    handleRenameArchived,
    handleConfirmTx,
    handleDiscardTx,
    setIncludeContext,
    setCurrentTitle,
    reloadUsage,
  }

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>
}

export function useChat(): ChatContextValue {
  const ctx = useContext(ChatContext)
  if (!ctx) throw new Error("useChat must be used within ChatProvider")
  return ctx
}
