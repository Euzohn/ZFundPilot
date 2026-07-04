import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { RiskReport, Advice } from "@/api/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { pct, pnlColor } from "@/lib/format"
import { ShieldAlert, AlertTriangle, Info, Lightbulb, Bot, Send, Search } from "lucide-react"
import type { ReactNode } from "react"
import { useRef, useEffect, useState } from "react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

function MetricCard({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <Card className="card-hover">
      <CardContent className="p-4 md:p-5">
        <p className="text-xs font-medium text-muted-foreground">{label}</p>
        <p className={`mt-1 text-lg md:text-xl font-bold tabular-nums ${color ?? ""}`}>{value}</p>
        {sub && <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p>}
      </CardContent>
    </Card>
  )
}

const FLAG_STYLES: Record<string, { icon: ReactNode; variant: "destructive" | "warning" | "default" }> = {
  danger: { icon: <ShieldAlert className="h-5 w-5 text-red-500" />, variant: "destructive" },
  warning: { icon: <AlertTriangle className="h-5 w-5 text-amber-500" />, variant: "warning" },
  info: { icon: <Info className="h-5 w-5 text-blue-500" />, variant: "default" },
}

export default function Risk() {
  const { data: report, loading: rl } = useApi<RiskReport>(() => api.getRiskReport())
  const { data: advice, loading: al } = useApi<Advice[]>(() => api.getRebalanceAdvice())

  if (rl || !report) return <div className="py-20 text-center text-muted-foreground">加载中...</div>

  return (
    <div className="space-y-6">
      <h1 className="text-xl md:text-2xl font-bold">风险与建议</h1>

      {/* Metrics */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 md:gap-4">
        <MetricCard label="最大回撤" value={report.max_drawdown != null ? pct(report.max_drawdown) : "数据不足"} color={pnlColor(report.max_drawdown ?? 0)} />
        <MetricCard label="年化波动率" value={report.volatility != null ? pct(report.volatility) : "数据不足"} />
        <MetricCard label="最大单基金占比" value={pct(report.max_single_weight)} sub={report.max_single_name} />
        <MetricCard label="集中度 HHI" value={report.hhi.toFixed(3)} />
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 md:gap-4">
        <MetricCard label="权益类占比" value={pct(report.equity_weight)} />
        <MetricCard label="债券类占比" value={pct(report.bond_weight)} />
        <MetricCard label="QDII 占比" value={pct(report.qdii_weight)} />
      </div>

      {/* Risk flags */}
      <Card>
        <CardHeader><CardTitle className="text-base">风险提示</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          {report.flags.map((f, i) => {
            const style = FLAG_STYLES[f.level] ?? FLAG_STYLES.info
            return (
              <div key={i} className="flex items-start gap-3 rounded-md border p-3">
                {style.icon}
                <div>
                  <p className="font-medium">
                    <Badge variant={style.variant} className="mr-2">{f.title}</Badge>
                  </p>
                  <p className="mt-1 text-sm text-muted-foreground">{f.detail}</p>
                </div>
              </div>
            )
          })}
        </CardContent>
      </Card>

      {/* Rebalance advice */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Lightbulb className="h-5 w-5 text-amber-500" />
            结构优化建议
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">以下为组合结构建议，非交易指令。</p>
          {al && advice && advice.length > 0 ? (
            advice.map((a, i) => (
              <div key={i} className="flex items-start gap-3 rounded-md border p-3">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-blue-100 text-xs font-bold text-blue-600">
                  {i + 1}
                </span>
                <div>
                  <Badge variant="outline" className="mr-2">{a.category}</Badge>
                  <span className="text-sm text-muted-foreground">{a.text}</span>
                </div>
              </div>
            ))
          ) : (
            <p className="py-4 text-center text-sm text-muted-foreground">暂无建议</p>
          )}
        </CardContent>
      </Card>

      {/* AI 投顾对话 */}
      <AIChatPanel />
    </div>
  )
}

// ---------------------------------------------------------------------------
// AI 对话面板
// ---------------------------------------------------------------------------
interface ChatMessage {
  role: "user" | "assistant"
  content: string
}

const QUICK_PROMPTS = [
  "分析当前组合的风险",
  "给出调仓建议",
  "科技板块最近怎么样？",
]

function AIChatPanel() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState("")
  const [streaming, setStreaming] = useState(false)
  const [searching, setSearching] = useState(false)
  const { data: aiConfig } = useApi(() => api.getAIConfig(), [])
  const chatEndRef = useRef<HTMLDivElement>(null)

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
      await api.streamChat(
        newMessages.map((m) => ({ role: m.role, content: m.content })),
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
    }
  }

  const configured = aiConfig?.base_url && aiConfig?.model

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Bot className="h-5 w-5 text-blue-500" />
          AI 投顾对话
        </CardTitle>
        <p className="text-sm text-muted-foreground">
          基于实时资讯 + 当前持仓数据，给出风险分析与调仓建议
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        {!configured ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            请先到「设置」页面配置 AI 模型 API
          </p>
        ) : (
          <>
            {/* 消息列表 */}
            <div className="max-h-[400px] overflow-y-auto space-y-3 rounded-lg border bg-slate-50/50 p-4">
              {messages.length === 0 && (
                <p className="py-6 text-center text-sm text-muted-foreground">
                  开始对话吧！AI 会先搜索最新市场资讯，再结合你的持仓给出建议。
                </p>
              )}
              {messages.map((msg, i) => (
                <div key={i} className={msg.role === "user" ? "text-right" : "text-left"}>
                  <div
                    className={
                      msg.role === "user"
                        ? "inline-block max-w-[85%] rounded-lg bg-blue-600 px-3 py-2 text-sm text-white"
                        : "inline-block max-w-[85%] rounded-lg bg-white border px-3 py-2 text-sm"
                    }
                  >
                    {msg.role === "assistant" ? (
                      <div className="prose prose-sm max-w-none prose-p:my-1 prose-ul:my-1 prose-ol:my-1 prose-li:my-0 prose-headings:mb-1 prose-headings:mt-2">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content || "..."}</ReactMarkdown>
                      </div>
                    ) : (
                      msg.content
                    )}
                  </div>
                </div>
              ))}
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
            <div className="flex flex-wrap gap-2">
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
            <div className="flex gap-2">
              <Input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault()
                    handleSend()
                  }
                }}
                placeholder="输入问题，如「我的科技基金占比太高怎么办？」"
                disabled={streaming}
              />
              <Button
                onClick={() => handleSend()}
                disabled={streaming || !input.trim()}
                size="icon"
                className="shrink-0"
              >
                <Send className="h-4 w-4" />
              </Button>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}
