import { useState, useEffect } from "react"
import { getChannels, saveChannels, getDefaultChannels } from "@/lib/channels"
import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import { clearToken } from "@/lib/auth"
import { Card, CardContent, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { toast } from "sonner"
import {
  ChevronUp, ChevronDown, Plus, Trash2, RotateCcw,
  KeyRound, Bot, ShoppingCart, ShieldCheck, Save,
} from "lucide-react"

function detectProvider(baseUrl: string): string {
  const url = baseUrl.toLowerCase()
  if (url.includes("moonshot") || url.includes("kimi")) return "Kimi (月之暗面)"
  if (url.includes("bigmodel") || url.includes("zhipu") || url.includes("glm")) return "智谱 GLM"
  if (url.includes("dashscope") || url.includes("aliyun")) return "通义千问"
  if (url.includes("deepseek")) return "DeepSeek（不支持联网搜索）"
  return "通用 OpenAI 兼容"
}

function SectionHeader({ icon: Icon, title, desc }: { icon: any; title: string; desc?: string }) {
  return (
    <div className="border-l-2 border-l-blue-500 pl-4">
      <div className="flex items-center gap-2">
        <Icon className="h-4 w-4 text-blue-600 shrink-0" />
        <CardTitle className="text-sm font-semibold tracking-tight">{title}</CardTitle>
      </div>
      {desc && <p className="mt-0.5 text-xs text-muted-foreground">{desc}</p>}
    </div>
  )
}

export default function Settings() {
  // Channels
  const [channels, setChannels] = useState<string[]>(() => getChannels())
  const [newChannel, setNewChannel] = useState("")

  // Auth
  const { data: authStatus } = useApi(() => api.getAuthStatus(), [])
  const [currentPwd, setCurrentPwd] = useState("")
  const [newPwd, setNewPwd] = useState("")
  const [confirmPwd, setConfirmPwd] = useState("")
  const [changingPwd, setChangingPwd] = useState(false)

  // AI config
  const { data: aiConfig, reload: reloadAIConfig } = useApi(() => api.getAIConfig(), [])
  const [aiBaseUrl, setAiBaseUrl] = useState("")
  const [aiApiKey, setAiApiKey] = useState("")
  const [aiModel, setAiModel] = useState("")
  const [aiWebSearch, setAiWebSearch] = useState(true)
  const [savingAI, setSavingAI] = useState(false)

  useEffect(() => {
    if (aiConfig) {
      setAiBaseUrl(aiConfig.base_url)
      setAiModel(aiConfig.model)
      setAiWebSearch(aiConfig.web_search)
    }
  }, [aiConfig])

  // --- Channels ---
  const moveUp = (i: number) => {
    if (i === 0) return
    const next = [...channels]
    ;[next[i - 1], next[i]] = [next[i], next[i - 1]]
    setChannels(next)
    saveChannels(next)
  }

  const moveDown = (i: number) => {
    if (i === channels.length - 1) return
    const next = [...channels]
    ;[next[i + 1], next[i]] = [next[i], next[i + 1]]
    setChannels(next)
    saveChannels(next)
  }

  const remove = (i: number) => {
    const next = channels.filter((_, idx) => idx !== i)
    setChannels(next)
    saveChannels(next)
  }

  const add = () => {
    const name = newChannel.trim()
    if (!name) return
    if (channels.includes(name)) { toast.warning("该渠道已存在"); return }
    const next = [...channels, name]
    setChannels(next)
    setNewChannel("")
    saveChannels(next)
  }

  const handleReset = () => {
    const defaults = getDefaultChannels()
    setChannels(defaults)
    saveChannels(defaults)
    toast.success("已恢复默认渠道顺序")
  }

  // --- Password ---
  const handleChangePassword = async () => {
    if (!currentPwd) { toast.error("请输入当前密码"); return }
    if (newPwd.length < 6) { toast.error("新密码至少 6 位"); return }
    if (newPwd !== confirmPwd) { toast.error("两次输入的新密码不一致"); return }
    setChangingPwd(true)
    try {
      await api.changePassword(currentPwd, newPwd)
      toast.success("密码已修改，请重新登录")
      setTimeout(() => { clearToken(); window.location.reload() }, 1500)
    } catch (e) { toast.error(`修改失败: ${e}`) }
    finally { setChangingPwd(false) }
  }

  // --- AI config ---
  const handleSaveAI = async () => {
    if (!aiBaseUrl.trim() || !aiModel.trim()) { toast.error("Base URL 和模型 ID 不能为空"); return }
    setSavingAI(true)
    try {
      await api.updateAIConfig(aiBaseUrl.trim(), aiApiKey, aiModel.trim(), aiWebSearch)
      setAiApiKey("")
      reloadAIConfig()
      toast.success("AI 配置已保存")
    } catch (e) { toast.error(`保存失败: ${e}`) }
    finally { setSavingAI(false) }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-xl md:text-2xl font-bold tracking-tight">设置</h1>

      <Card className="overflow-hidden">
        <div className="divide-y divide-slate-100">
          {/* ── 购买渠道 ── */}
          <div className="px-5 py-5 space-y-3">
            <SectionHeader icon={ShoppingCart} title="购买渠道顺序" desc="排在前面的渠道作为交易表单的默认选项，上下箭头调整顺序，自动保存" />

            <div className="space-y-1">
              {channels.map((ch, i) => (
                <div key={ch} className="flex items-center gap-2 rounded-lg border border-slate-100 bg-white px-3 py-2 transition-colors hover:border-slate-200">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-slate-100 text-xs font-medium text-slate-500">
                    {i + 1}
                  </span>
                  <button onClick={() => moveUp(i)} disabled={i === 0}
                    className="flex h-5 w-5 items-center justify-center rounded text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 disabled:opacity-20 disabled:cursor-not-allowed">
                    <ChevronUp className="h-3.5 w-3.5" />
                  </button>
                  <button onClick={() => moveDown(i)} disabled={i === channels.length - 1}
                    className="flex h-5 w-5 items-center justify-center rounded text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 disabled:opacity-20 disabled:cursor-not-allowed">
                    <ChevronDown className="h-3.5 w-3.5" />
                  </button>
                  <span className="flex-1 text-sm font-medium">{ch}</span>
                  <span className="hidden sm:inline text-xs text-slate-400">{i === 0 ? "默认" : ""}</span>
                  <button onClick={() => remove(i)}
                    className="flex h-6 w-6 items-center justify-center rounded text-slate-300 transition-colors hover:bg-red-50 hover:text-red-500">
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>

            <div className="flex flex-wrap gap-2">
              <div className="flex flex-1 gap-2 min-w-0">
                <Input
                  value={newChannel}
                  onChange={(e) => setNewChannel(e.target.value)}
                  placeholder="新增渠道名称"
                  onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add() } }}
                  className="h-8 text-xs max-w-[180px]"
                />
                <Button variant="outline" size="sm" onClick={add} className="h-8 shrink-0">
                  <Plus className="mr-1 h-3.5 w-3.5" /> 添加
                </Button>
              </div>
              <Button variant="outline" size="sm" onClick={handleReset} className="h-8 shrink-0">
                <RotateCcw className="mr-1 h-3.5 w-3.5" /> 恢复默认
              </Button>
            </div>
          </div>

          {/* ── 安全 ── */}
          {authStatus?.required && (
            <div className="px-5 py-5 space-y-3">
              <SectionHeader icon={ShieldCheck} title="安全" desc="修改密码后所有设备需重新登录" />

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div>
                  <Label className="mb-1 block text-xs text-slate-500">当前密码</Label>
                  <Input type="password" value={currentPwd} onChange={(e) => setCurrentPwd(e.target.value)}
                    className="h-8 text-xs" placeholder="输入当前密码" autoFocus />
                </div>
                <div>
                  <Label className="mb-1 block text-xs text-slate-500">新密码</Label>
                  <Input type="password" value={newPwd} onChange={(e) => setNewPwd(e.target.value)}
                    className="h-8 text-xs" placeholder="至少 6 位" />
                </div>
                <div>
                  <Label className="mb-1 block text-xs text-slate-500">确认新密码</Label>
                  <Input type="password" value={confirmPwd} onChange={(e) => setConfirmPwd(e.target.value)}
                    className="h-8 text-xs" placeholder="再次输入新密码"
                    onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); handleChangePassword() } }} />
                </div>
              </div>

              <Button size="sm" onClick={handleChangePassword} disabled={changingPwd} variant="outline">
                <KeyRound className="mr-1.5 h-3.5 w-3.5" /> {changingPwd ? "修改中..." : "修改密码"}
              </Button>
            </div>
          )}

          {/* ── AI 投顾 ── */}
          <div className="px-5 py-5 space-y-3">
            <SectionHeader icon={Bot} title="AI 投顾配置" desc="配置 OpenAI 兼容 API 后，可在「风险与建议」页面与 AI 对话" />

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div>
                <Label className="mb-1 block text-xs text-slate-500">API Base URL</Label>
                <Input value={aiBaseUrl} onChange={(e) => setAiBaseUrl(e.target.value)}
                  className="h-8 text-xs" placeholder="https://api.moonshot.cn/v1" />
              </div>
              <div>
                <Label className="mb-1 block text-xs text-slate-500">API Key</Label>
                <Input type="password" value={aiApiKey} onChange={(e) => setAiApiKey(e.target.value)}
                  className="h-8 text-xs"
                  placeholder={aiConfig?.has_key ? "已配置，输入新值覆盖" : "sk-..."} />
              </div>
              <div>
                <Label className="mb-1 block text-xs text-slate-500">模型 ID</Label>
                <Input value={aiModel} onChange={(e) => setAiModel(e.target.value)}
                  className="h-8 text-xs" placeholder="kimi-k2.6 / glm-4-plus / qwen-plus" />
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <label className="flex items-center gap-1.5 text-xs cursor-pointer select-none">
                <input type="checkbox" checked={aiWebSearch} onChange={(e) => setAiWebSearch(e.target.checked)} className="rounded" />
                启用联网搜索
              </label>
              {aiWebSearch && aiBaseUrl && (
                <span className="text-xs text-blue-600 bg-blue-50 px-2 py-0.5 rounded-full">
                  {detectProvider(aiBaseUrl)}
                </span>
              )}
            </div>

            <Button size="sm" onClick={handleSaveAI} disabled={savingAI}>
              <Save className="mr-1.5 h-3.5 w-3.5" /> {savingAI ? "保存中..." : "保存配置"}
            </Button>
          </div>
        </div>
      </Card>
    </div>
  )
}