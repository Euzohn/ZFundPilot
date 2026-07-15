import { useState, useEffect } from "react"
import { getChannels, getChannelsAsync, saveChannels, getDefaultChannels } from "@/lib/channels"
import { getChannelColors, getChannelColorsAsync, saveChannelColors, getDefaultChannelColors, getPalette } from "@/lib/channelColors"
import { getColorTheme, getColorThemeAsync, saveColorTheme, applyColorTheme, type ColorTheme } from "@/lib/colorTheme"
import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import { clearToken } from "@/lib/auth"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import LogoSpinner from "@/components/LogoSpinner"
import { toast } from "sonner"
import { cn } from "@/lib/utils"
import type { AIUsageStats, AIUsageDaily, KeywordMaps, KeywordEntry, SchedulerStatus } from "@/api/types"
import {
  ChevronUp, ChevronDown, Plus, Trash2, RotateCcw,
  KeyRound, Bot, ShoppingCart, ShieldCheck, Save, RefreshCw,
  SlidersHorizontal, LogOut, Loader2, CheckCircle2, XCircle, Zap,
  Search, X, Palette, UserCircle, Clock,
} from "lucide-react"

function detectProvider(baseUrl: string): string {
  const url = baseUrl.toLowerCase()
  if (url.includes("moonshot") || url.includes("kimi")) return "Kimi (月之暗面)"
  if (url.includes("bigmodel") || url.includes("zhipu") || url.includes("glm")) return "智谱 GLM"
  if (url.includes("dashscope") || url.includes("aliyun") || url.includes("aliyuncs") || url.includes("maas")) return "通义千问 (百炼)"
  if (url.includes("deepseek")) return "DeepSeek"
  return "通用 OpenAI 兼容"
}

function formatTokens(n: number): string {
  if (n < 1000) return String(n)
  if (n < 1000000) return (n / 1000).toFixed(n < 10000 ? 1 : 0) + "k"
  return (n / 1000000).toFixed(1) + "m"
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
  return `${day} 天前`
}

function Sparkline({ data }: { data: number[] }) {
  if (!data || data.length < 2) return null
  const w = 200, h = 40
  const max = Math.max(...data, 1)
  const min = Math.min(...data, 0)
  const range = max - min || 1
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * w
    const y = h - 2 - ((v - min) / range) * (h - 4)
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(" ")
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-10" preserveAspectRatio="none">
      <polyline points={pts} fill="none" stroke="#3b82f6" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

const PROVIDER_PRESETS = [
  { name: "智谱 GLM", baseUrl: "https://open.bigmodel.cn/v1", model: "glm-4-plus" },
  { name: "Kimi", baseUrl: "https://api.moonshot.cn/v1", model: "moonshot-v1-8k" },
  { name: "DeepSeek", baseUrl: "https://api.deepseek.com/v1", model: "deepseek-chat" },
  { name: "通义千问", baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1", model: "qwen-plus" },
]

export default function Settings() {
  // Channels
  const [channels, setChannels] = useState<string[]>(() => getChannels())
  const [newChannel, setNewChannel] = useState("")
  // Channel colors
  const [channelColors, setChannelColors] = useState<Record<string, string>>(() => getChannelColors())
  const palette = getPalette()
  // Color theme
  const [colorTheme, setColorTheme] = useState<ColorTheme>(() => getColorTheme())
  const [colorThemeLoading, setColorThemeLoading] = useState(false)

  // Scheduler
  const { data: schedulerStatus, reload: reloadScheduler } = useApi<SchedulerStatus>(() => api.getSchedulerStatus(), [])
  const [schedulerToggling, setSchedulerToggling] = useState(false)

  // 页面加载时尝试从服务端同步渠道设置
  useEffect(() => {
    getChannelsAsync().then(setChannels).catch(() => {})
    getChannelColorsAsync().then(setChannelColors).catch(() => {})
    getColorThemeAsync().then((t) => { setColorTheme(t); applyColorTheme(t) }).catch(() => {})
  }, [])

  // Auth
  const { data: authStatus } = useApi(() => api.getAuthStatus(), [])
  const [currentPwd, setCurrentPwd] = useState("")
  const [newPwd, setNewPwd] = useState("")
  const [confirmPwd, setConfirmPwd] = useState("")
  const [changingPwd, setChangingPwd] = useState(false)
  const [newUsername, setNewUsername] = useState("")
  const [usernamePwd, setUsernamePwd] = useState("")
  const [changingUsername, setChangingUsername] = useState(false)

  // AI config
  const { data: aiConfig, reload: reloadAIConfig } = useApi(() => api.getAIConfig(), [])
  const [aiBaseUrl, setAiBaseUrl] = useState("")
  const [aiApiKey, setAiApiKey] = useState("")
  const [aiModel, setAiModel] = useState("")
  const [aiWebSearch, setAiWebSearch] = useState(true)
  const [savingAI, setSavingAI] = useState(false)
  const [resettingSectors, setResettingSectors] = useState(false)

  // AI test connection
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; provider?: string; model?: string; has_search?: boolean; error?: string } | null>(null)

  // AI usage
  const { data: usageStats } = useApi<AIUsageStats>(() => api.getAIUsage(), [])
  const { data: usageDaily } = useApi<AIUsageDaily[]>(() => api.getAIUsageDaily(7), [])

  useEffect(() => {
    if (aiConfig) {
      setAiBaseUrl(aiConfig.base_url)
      setAiModel(aiConfig.model)
      setAiWebSearch(aiConfig.web_search)
    }
  }, [aiConfig])

  // Clear test result when config changes
  useEffect(() => { setTestResult(null) }, [aiBaseUrl, aiApiKey, aiModel, aiWebSearch])

  // --- Channels ---
  const moveUp = async (i: number) => {
    if (i === 0) return
    const next = [...channels]
    ;[next[i - 1], next[i]] = [next[i], next[i - 1]]
    setChannels(next); await saveChannels(next)
  }
  const moveDown = async (i: number) => {
    if (i === channels.length - 1) return
    const next = [...channels]
    ;[next[i + 1], next[i]] = [next[i], next[i + 1]]
    setChannels(next); await saveChannels(next)
  }
  const remove = async (i: number) => {
    const next = channels.filter((_, idx) => idx !== i)
    setChannels(next); await saveChannels(next)
  }
  const add = async () => {
    const name = newChannel.trim()
    if (!name) return
    if (channels.includes(name)) { toast.warning("该渠道已存在"); return }
    const next = [...channels, name]
    setChannels(next); setNewChannel(""); await saveChannels(next)
  }
  const handleReset = async () => {
    const defaults = getDefaultChannels()
    setChannels(defaults); await saveChannels(defaults)
    toast.success("已恢复默认渠道顺序")
  }

  // --- Channel colors ---
  const handleColorChange = async (channel: string, color: string) => {
    const next = { ...channelColors, [channel]: color }
    setChannelColors(next)
    await saveChannelColors(next)
  }
  const handleColorsReset = async () => {
    const defaults = getDefaultChannelColors()
    setChannelColors(defaults)
    await saveChannelColors(defaults)
    toast.success("已恢复默认渠道颜色")
  }

  // --- Color theme ---
  const handleThemeChange = async (theme: ColorTheme) => {
    setColorTheme(theme)
    applyColorTheme(theme)
    setColorThemeLoading(true)
    try {
      await saveColorTheme(theme)
    } catch { /* server unavailable */ }
    finally { setColorThemeLoading(false) }
  }

  // --- Scheduler ---
  const handleSchedulerToggle = async () => {
    if (!schedulerStatus) return
    setSchedulerToggling(true)
    try {
      await api.toggleScheduler(!schedulerStatus.enabled)
      await reloadScheduler()
      toast.success(schedulerStatus.enabled ? "定时更新已暂停" : "定时更新已启用")
    } catch (e) { toast.error(`操作失败: ${e}`) }
    finally { setSchedulerToggling(false) }
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

  const handleChangeUsername = async () => {
    if (newUsername.trim().length < 2) { toast.error("用户名至少 2 位"); return }
    if (!usernamePwd) { toast.error("请输入当前密码"); return }
    setChangingUsername(true)
    try {
      await api.changeUsername(usernamePwd, newUsername.trim())
      toast.success("用户名已修改，请重新登录")
      setTimeout(() => { clearToken(); window.location.reload() }, 1500)
    } catch (e) { toast.error(`修改失败: ${e}`) }
    finally { setChangingUsername(false) }
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

  const handleTestConnection = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const res = await api.testAIConnection()
      setTestResult(res)
      if (res.ok) toast.success(`连接成功 · ${res.provider} · ${res.model}`)
      else toast.error(`连接失败: ${res.error}`)
    } catch (e) {
      toast.error(`测试失败: ${e}`)
    } finally {
      setTesting(false)
    }
  }

  const handleResetSectors = async () => {
    setResettingSectors(true)
    try {
      const res = await api.resetSectors()
      toast.success(`已重新计算 ${res.reset} 个基金的板块`)
    } catch (e) { toast.error(`重置失败: ${e}`) }
    finally { setResettingSectors(false) }
  }

  // --- Keyword Maps ---
  const [keywordMaps, setKeywordMaps] = useState<KeywordMaps | null>(null)
  const [kwTab, setKwTab] = useState("sector")
  const [kwSearch, setKwSearch] = useState("")
  const [kwShowDefaults, setKwShowDefaults] = useState(false)
  const [newKwKeyword, setNewKwKeyword] = useState("")
  const [newKwMapped, setNewKwMapped] = useState("")
  const [kwSaving, setKwSaving] = useState(false)

  const { data: kwData } = useApi(() => api.getKeywordMaps(), [])
  useEffect(() => {
    if (kwData && !keywordMaps) setKeywordMaps(kwData)
  }, [kwData])

  const kwCustom = keywordMaps ? (kwTab === "sector" ? keywordMaps.sector_custom : keywordMaps.type_custom) : []
  const kwDefaults = keywordMaps ? (kwTab === "sector" ? keywordMaps.sector_defaults : keywordMaps.type_defaults) : []
  const kwAvailable = keywordMaps ? (kwTab === "sector" ? keywordMaps.available_sectors : keywordMaps.available_types) : []

  const kwFilteredDefaults = kwDefaults.filter((e) => !kwSearch || e.keyword.includes(kwSearch) || e.mapped.includes(kwSearch))

  const addCustomKeyword = async () => {
    const keyword = newKwKeyword.trim()
    const mapped = newKwMapped.trim()
    if (!keyword || !mapped) { toast.warning("请填写关键词和映射值"); return }
    if (kwCustom.some((e) => e.keyword === keyword)) { toast.warning("该关键词已存在"); return }
    const next = [...kwCustom, { keyword, mapped }]
    const typeCustom = kwTab === "sector" ? keywordMaps!.type_custom : next
    const sectorCustom = kwTab === "sector" ? next : keywordMaps!.sector_custom
    setKeywordMaps({ ...keywordMaps!, [kwTab === "sector" ? "sector_custom" : "type_custom"]: next })
    setNewKwKeyword(""); setNewKwMapped("")
    try { await api.saveKeywordMaps(JSON.stringify(typeCustom), JSON.stringify(sectorCustom)) } catch {}
  }

  const deleteCustomKeyword = async (idx: number) => {
    const next = kwCustom.filter((_, i) => i !== idx)
    const typeCustom = kwTab === "sector" ? keywordMaps!.type_custom : next
    const sectorCustom = kwTab === "sector" ? next : keywordMaps!.sector_custom
    setKeywordMaps({ ...keywordMaps!, [kwTab === "sector" ? "sector_custom" : "type_custom"]: next })
    try { await api.saveKeywordMaps(JSON.stringify(typeCustom), JSON.stringify(sectorCustom)) } catch {}
  }

  const moveCustomKeyword = async (idx: number, dir: -1 | 1) => {
    const next = [...kwCustom]
    const target = idx + dir
    if (target < 0 || target >= next.length) return
    ;[next[idx], next[target]] = [next[target], next[idx]]
    const typeCustom = kwTab === "sector" ? keywordMaps!.type_custom : next
    const sectorCustom = kwTab === "sector" ? next : keywordMaps!.sector_custom
    setKeywordMaps({ ...keywordMaps!, [kwTab === "sector" ? "sector_custom" : "type_custom"]: next })
    try { await api.saveKeywordMaps(JSON.stringify(typeCustom), JSON.stringify(sectorCustom)) } catch {}
  }

  const resetCustomKeywords = async () => {
    const typeCustom = kwTab === "sector" ? keywordMaps!.type_custom : []
    const sectorCustom = kwTab === "sector" ? [] : keywordMaps!.sector_custom
    setKeywordMaps({ ...keywordMaps!, [kwTab === "sector" ? "sector_custom" : "type_custom"]: [] })
    try { await api.saveKeywordMaps(JSON.stringify(typeCustom), JSON.stringify(sectorCustom)); toast.success("已重置自定义关键词") } catch {}
  }

  const authRequired = authStatus?.required

  return (
    <div className="space-y-6">
      <h1 className="text-xl md:text-2xl font-bold tracking-tight">设置</h1>

      <Tabs defaultValue="ai">
        <TabsList className={cn("grid w-full sm:inline-flex sm:w-auto", authRequired ? "grid-cols-3" : "grid-cols-2")}>
          {authRequired && (
            <TabsTrigger value="account" className="gap-1.5">
              <ShieldCheck className="h-4 w-4" />
              <span className="hidden sm:inline">账户与安全</span><span className="sm:hidden">账户</span>
            </TabsTrigger>
          )}
          <TabsTrigger value="ai" className="gap-1.5">
            <Bot className="h-4 w-4" />
            <span className="hidden sm:inline">AI 投顾</span><span className="sm:hidden">AI</span>
          </TabsTrigger>
          <TabsTrigger value="prefs" className="gap-1.5">
            <SlidersHorizontal className="h-4 w-4" />
            <span className="hidden sm:inline">偏好设置</span><span className="sm:hidden">偏好</span>
          </TabsTrigger>
        </TabsList>

        {/* ── 账户与安全 ── */}
        {authRequired && (
          <TabsContent value="account">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="flex items-center gap-2 text-base">
                  <ShieldCheck className="h-5 w-5 text-blue-500" />
                  账户与安全
                </CardTitle>
                <p className="text-sm text-muted-foreground">
                  当前用户名：<span className="font-medium text-slate-700">{authStatus?.username || "—"}</span>
                </p>
              </CardHeader>
              <CardContent className="space-y-5">
                {/* 修改用户名 */}
                <div className="space-y-2">
                  <Label className="text-xs font-medium text-slate-600">修改用户名</Label>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <Input value={newUsername} onChange={(e) => setNewUsername(e.target.value)}
                      className="h-8 text-xs" placeholder="新用户名（至少 2 位）" />
                    <Input type="password" value={usernamePwd} onChange={(e) => setUsernamePwd(e.target.value)}
                      className="h-8 text-xs" placeholder="当前密码"
                      onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); handleChangeUsername() } }} />
                  </div>
                  <Button size="sm" onClick={handleChangeUsername} disabled={changingUsername} variant="outline">
                    <UserCircle className="mr-1.5 h-3.5 w-3.5" /> {changingUsername ? "修改中..." : "修改用户名"}
                  </Button>
                </div>

                <div className="border-t pt-4" />

                {/* 修改密码 */}
                <div className="space-y-2">
                  <Label className="text-xs font-medium text-slate-600">修改密码</Label>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <div>
                      <Label className="mb-1 block text-xs text-slate-500">当前密码</Label>
                      <Input type="password" value={currentPwd} onChange={(e) => setCurrentPwd(e.target.value)}
                        className="h-8 text-xs" placeholder="输入当前密码" />
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
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" onClick={handleChangePassword} disabled={changingPwd} variant="outline">
                      <KeyRound className="mr-1.5 h-3.5 w-3.5" /> {changingPwd ? "修改中..." : "修改密码"}
                    </Button>
                    <Button size="sm" variant="outline" className="text-red-500 hover:bg-red-50 hover:text-red-600"
                      onClick={() => { clearToken(); window.location.reload() }}>
                      <LogOut className="mr-1.5 h-3.5 w-3.5" /> 退出登录
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          </TabsContent>
        )}

        {/* ── AI 投顾 ── */}
        <TabsContent value="ai">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <Bot className="h-5 w-5 text-blue-500" />
                AI 投顾配置
              </CardTitle>
              <p className="text-sm text-muted-foreground">配置 OpenAI 兼容 API 后，可在「AI 助手」页面对话并录入交易</p>
            </CardHeader>
            <CardContent className="space-y-5">
              {/* API 配置 */}
              <div className="space-y-3">
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
                      className="h-8 text-xs" placeholder="glm-4-plus / moonshot-v1-8k / deepseek-chat" />
                  </div>
                </div>

                {/* 平台快捷预设 */}
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs text-muted-foreground">快捷填充：</span>
                  {PROVIDER_PRESETS.map((p) => (
                    <button
                      key={p.name}
                      type="button"
                      onClick={() => { setAiBaseUrl(p.baseUrl); setAiModel(p.model) }}
                      className="rounded-full border border-slate-200 bg-white px-2.5 py-0.5 text-xs text-slate-600 transition-colors hover:border-blue-300 hover:bg-blue-50 hover:text-blue-600 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]"
                    >
                      {p.name}
                    </button>
                  ))}
                </div>

                {/* 联网搜索 */}
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

                {/* 操作按钮 */}
                <div className="flex flex-wrap items-center gap-2">
                  <Button size="sm" onClick={handleSaveAI} disabled={savingAI}>
                    <Save className="mr-1.5 h-3.5 w-3.5" /> {savingAI ? "保存中..." : "保存配置"}
                  </Button>
                  <Button size="sm" variant="outline" onClick={handleTestConnection} disabled={testing}>
                    {testing ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Zap className="mr-1.5 h-3.5 w-3.5" />}
                    {testing ? "测试中..." : "测试连接"}
                  </Button>
                </div>

                {/* 测试结果 */}
                {testResult && (
                  <div className={cn(
                    "flex items-center gap-1.5 rounded-md px-3 py-2 text-xs",
                    testResult.ok ? "bg-green-50 text-green-700 border border-green-200" : "bg-red-50 text-red-600 border border-red-200"
                  )}>
                    {testResult.ok
                      ? <><CheckCircle2 className="h-3.5 w-3.5 shrink-0" /> 连接成功 · {testResult.provider} · {testResult.model}{testResult.has_search ? " · 联网搜索已启用" : ""}</>
                      : <><XCircle className="h-3.5 w-3.5 shrink-0" /> {testResult.error}</>
                    }
                  </div>
                )}
              </div>

              {/* 分隔线 */}
              <div className="border-t border-slate-100" />

              {/* Token 用量 */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium">Token 用量</p>
                  {usageStats && (
                    <p className="text-xs text-muted-foreground">
                      今日 <span className="font-medium text-foreground">{formatTokens(usageStats.today)}</span>
                      {" · "}累计 <span className="font-medium text-foreground">{formatTokens(usageStats.total)}</span>
                    </p>
                  )}
                </div>

                {/* 7 天趋势 sparkline */}
                {usageDaily && usageDaily.length >= 2 ? (
                  <div className="rounded-lg border bg-slate-50/50 px-3 py-2">
                    <Sparkline data={usageDaily.map((d) => d.tokens)} />
                    <div className="flex justify-between text-[10px] text-muted-foreground mt-0.5">
                      <span>{usageDaily[0].date.slice(5)}</span>
                      <span>近 7 天</span>
                      <span>{usageDaily[usageDaily.length - 1].date.slice(5)}</span>
                    </div>
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground py-2">暂无用量数据</p>
                )}

                {/* 最近调用表格 */}
                {usageStats && usageStats.recent.length > 0 ? (
                  <div className="overflow-x-auto rounded-md border">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className="text-xs">时间</TableHead>
                          <TableHead className="text-xs">模型</TableHead>
                          <TableHead className="text-xs text-right">入</TableHead>
                          <TableHead className="text-xs text-right">出</TableHead>
                          <TableHead className="text-xs text-right">总</TableHead>
                          <TableHead className="text-xs text-right">轮数</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {usageStats.recent.slice(0, 10).map((r) => (
                          <TableRow key={r.id}>
                            <TableCell className="text-xs text-muted-foreground whitespace-nowrap">{formatRelativeTime(r.created_at)}</TableCell>
                            <TableCell className="text-xs font-mono whitespace-nowrap">{r.model || "—"}</TableCell>
                            <TableCell className="text-xs text-right tabular-nums">{formatTokens(r.prompt_tokens)}</TableCell>
                            <TableCell className="text-xs text-right tabular-nums">{formatTokens(r.completion_tokens)}</TableCell>
                            <TableCell className="text-xs text-right tabular-nums font-medium">{formatTokens(r.total_tokens)}</TableCell>
                            <TableCell className="text-xs text-right tabular-nums">{r.turns}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                ) : (
                  !usageStats && <div className="flex justify-center py-4"><LogoSpinner className="h-8 w-8" /></div>
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── 偏好设置 ── */}
        <TabsContent value="prefs">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <SlidersHorizontal className="h-5 w-5 text-blue-500" />
                偏好设置
              </CardTitle>
              <p className="text-sm text-muted-foreground">购买渠道顺序与板块映射</p>
            </CardHeader>
            <CardContent className="space-y-5">
              {/* 购买渠道 */}
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <ShoppingCart className="h-4 w-4 text-muted-foreground" />
                  <p className="text-sm font-medium">购买渠道顺序</p>
                  <span className="text-xs text-muted-foreground">排在前面的为默认选项</span>
                </div>

                <div className="space-y-1">
                  {channels.map((ch, i) => (
                    <div key={ch} className="flex items-center gap-2 rounded-lg border border-slate-100 bg-white px-3 py-2 transition-colors hover:border-slate-200">
                      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-slate-100 text-xs font-medium text-slate-500">
                        {i + 1}
                      </span>
                      <button onClick={() => moveUp(i)} disabled={i === 0}
                        className="flex h-5 w-5 items-center justify-center rounded text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 disabled:opacity-20 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]">
                        <ChevronUp className="h-3.5 w-3.5" />
                      </button>
                      <button onClick={() => moveDown(i)} disabled={i === channels.length - 1}
                        className="flex h-5 w-5 items-center justify-center rounded text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700 disabled:opacity-20 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]">
                        <ChevronDown className="h-3.5 w-3.5" />
                      </button>
                      <span className="flex-1 text-sm font-medium">{ch}</span>
                      <span className="hidden sm:inline text-xs text-slate-400">{i === 0 ? "默认" : ""}</span>
                      <button onClick={() => remove(i)}
                        className="flex h-6 w-6 items-center justify-center rounded text-slate-300 transition-colors hover:bg-red-50 hover:text-red-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]">
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

              {/* 渠道颜色 */}
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <Palette className="h-4 w-4 text-muted-foreground" />
                  <p className="text-sm font-medium">渠道颜色</p>
                  <span className="text-xs text-muted-foreground">收益波动堆叠柱状图中各渠道的展示颜色</span>
                  <Button variant="ghost" size="sm" onClick={handleColorsReset} className="h-6 px-2 text-xs ml-auto shrink-0">
                    <RotateCcw className="mr-1 h-3 w-3" /> 恢复默认
                  </Button>
                </div>
                <div className="space-y-1">
                  {channels.map((ch) => (
                    <div key={ch} className="flex items-center gap-2 rounded-lg border border-slate-100 bg-white px-3 py-2">
                      <span className="flex-1 text-sm font-medium">{ch}</span>
                      <div className="flex items-center gap-1">
                        {palette.map(color => (
                          <button key={color} onClick={() => handleColorChange(ch, color)}
                            className={cn("h-5 w-5 rounded-full border-2 transition-transform hover:scale-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]",
                              channelColors[ch] === color ? "border-slate-400" : "border-transparent")}
                            style={{ background: color }} />
                        ))}
                      </div>
                      <input type="color" value={channelColors[ch] ?? "#3b82f6"}
                        onChange={(e) => handleColorChange(ch, e.target.value)}
                        className="h-6 w-6 rounded cursor-pointer border border-slate-200" />
                    </div>
                  ))}
                </div>
              </div>

              {/* 分隔线 */}
              <div className="border-t border-slate-100" />

              {/* 涨跌颜色 */}
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <Palette className="h-4 w-4 text-muted-foreground" />
                  <p className="text-sm font-medium">涨跌颜色</p>
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => handleThemeChange("international")}
                    disabled={colorThemeLoading}
                    className={cn(
                      "flex-1 rounded-lg border px-3 py-2 text-sm transition-colors disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]",
                      colorTheme === "international"
                        ? "border-blue-300 bg-blue-50 text-blue-700"
                        : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50"
                    )}
                  >
                    <span className="text-green-600 font-medium">▲</span> 绿涨
                    <span className="text-red-600 font-medium ml-2">▼</span> 红跌
                    <span className="block text-[11px] text-muted-foreground mt-0.5">国际惯例</span>
                  </button>
                  <button
                    onClick={() => handleThemeChange("china")}
                    disabled={colorThemeLoading}
                    className={cn(
                      "flex-1 rounded-lg border px-3 py-2 text-sm transition-colors disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]",
                      colorTheme === "china"
                        ? "border-blue-300 bg-blue-50 text-blue-700"
                        : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50"
                    )}
                  >
                    <span className="text-red-600 font-medium">▲</span> 红涨
                    <span className="text-green-600 font-medium ml-2">▼</span> 绿跌
                    <span className="block text-[11px] text-muted-foreground mt-0.5">国内 A 股惯例</span>
                  </button>
                </div>
              </div>

              {/* 分隔线 */}
              <div className="border-t border-slate-100" />

              {/* 定时任务 */}
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <Clock className="h-4 w-4 text-muted-foreground" />
                  <p className="text-sm font-medium">定时净值更新</p>
                  <span className="text-xs text-muted-foreground">工作日自动拉取最新净值</span>
                </div>
                {schedulerStatus ? (
                  <div className="space-y-2">
                    <div className="flex items-center gap-2">
                      <button
                        onClick={handleSchedulerToggle}
                        disabled={schedulerToggling}
                        className={cn(
                          "rounded-lg border px-3 py-1.5 text-sm transition-colors disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]",
                          schedulerStatus.enabled
                            ? "border-blue-300 bg-blue-50 text-blue-700"
                            : "border-slate-200 bg-white text-slate-500 hover:bg-slate-50"
                        )}
                      >
                        {schedulerToggling ? "切换中..." : schedulerStatus.enabled ? "已启用" : "已暂停"}
                      </button>
                      <span className="text-xs text-muted-foreground font-mono">
                        cron: {schedulerStatus.cron}
                      </span>
                    </div>
                    <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
                      {schedulerStatus.next_run && (
                        <span>下次运行: <span className="font-medium text-foreground">{schedulerStatus.next_run}</span></span>
                      )}
                      {schedulerStatus.last_run && (
                        <span>上次运行: <span className="font-medium text-foreground">{schedulerStatus.last_run}</span></span>
                      )}
                      {schedulerStatus.last_results && schedulerStatus.last_results.length > 0 && (
                        <span>
                          上次结果:{" "}
                          <span className="text-gain-600 font-medium">
                            {schedulerStatus.last_results.filter(r => r.ok).length} 成功
                          </span>
                          {" / "}
                          <span className="text-loss-600 font-medium">
                            {schedulerStatus.last_results.filter(r => !r.ok).length} 失败
                          </span>
                        </span>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="flex justify-center py-2"><LogoSpinner className="h-6 w-6" /></div>
                )}
              </div>
            </CardContent>
          </Card>

          {/* ── 关键词映射 ── */}
          {keywordMaps && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="flex items-center gap-2 text-base">
                  <Search className="h-5 w-5 text-blue-500" />
                  关键词映射
                </CardTitle>
                <p className="text-sm text-muted-foreground">添加自定义关键词，匹配时优先于默认规则</p>
              </CardHeader>
              <CardContent className="space-y-4">
                {/* Tab: 板块 / 类型 */}
                <div className="flex gap-1 rounded-lg bg-muted p-1 w-fit">
                  {([["sector", "板块关键词"], ["type", "类型关键词"]] as const).map(([key, label]) => (
                    <button
                      key={key}
                      type="button"
                      onClick={() => { setKwTab(key); setKwSearch("") }}
                      className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98] ${kwTab === key ? "bg-white text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
                    >
                      {label}
                    </button>
                  ))}
                </div>

                {/* 添加自定义 */}
                <div className="flex flex-wrap items-end gap-2">
                  <div className="flex-1 min-w-[120px]">
                    <Label className="mb-1 block text-xs text-muted-foreground">关键词</Label>
                    <Input value={newKwKeyword} onChange={(e) => setNewKwKeyword(e.target.value)}
                      placeholder="如 新能源车" className="h-8 text-xs"
                      onKeyDown={(e) => { if (e.key === "Enter") addCustomKeyword() }} />
                  </div>
                  <div className="flex-1 min-w-[120px]">
                    <Label className="mb-1 block text-xs text-muted-foreground">映射为</Label>
                    <select
                      value={newKwMapped}
                      onChange={(e) => setNewKwMapped(e.target.value)}
                      className="flex h-8 w-full rounded-md border border-input bg-background px-3 py-1 text-xs shadow-sm transition-colors placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                    >
                      <option value="">选择{kwTab === "sector" ? "板块" : "类型"}</option>
                      {kwAvailable.map((a) => <option key={a} value={a}>{a}</option>)}
                    </select>
                  </div>
                  <Button size="sm" onClick={addCustomKeyword} className="h-8 shrink-0">
                    <Plus className="mr-1 h-3.5 w-3.5" /> 添加
                  </Button>
                </div>

                {/* 自定义关键词列表 */}
                {kwCustom.length > 0 && (
                  <div className="space-y-1">
                    <p className="text-xs font-medium text-muted-foreground">自定义关键词（{kwCustom.length} 个）</p>
                    {kwCustom.map((e, i) => (
                      <div key={i} className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50/40 px-3 py-1.5">
                        <button onClick={() => moveCustomKeyword(i, -1)} disabled={i === 0}
                          className="flex h-5 w-5 items-center justify-center rounded text-slate-400 hover:bg-slate-100 disabled:opacity-20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]">
                          <ChevronUp className="h-3 w-3" />
                        </button>
                        <button onClick={() => moveCustomKeyword(i, 1)} disabled={i === kwCustom.length - 1}
                          className="flex h-5 w-5 items-center justify-center rounded text-slate-400 hover:bg-slate-100 disabled:opacity-20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]">
                          <ChevronDown className="h-3 w-3" />
                        </button>
                        <span className="text-sm font-medium flex-1">{e.keyword}</span>
                        <span className="text-xs text-muted-foreground">→</span>
                        <span className="text-sm font-medium text-blue-600">{e.mapped}</span>
                        <button onClick={() => deleteCustomKeyword(i)}
                          className="flex h-5 w-5 items-center justify-center rounded text-slate-300 hover:text-red-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]">
                          <X className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}

                {/* 默认关键词（默认展开） */}
                <div>
                  <button
                    type="button"
                    onClick={() => setKwShowDefaults(!kwShowDefaults)}
                    className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]"
                  >
                    {kwShowDefaults ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                    {kwShowDefaults ? "收起" : "展开"}默认关键词（{kwDefaults.length} 个）
                  </button>
                  {kwShowDefaults && (
                    <div className="mt-2 space-y-2">
                      <Input
                        value={kwSearch}
                        onChange={(e) => setKwSearch(e.target.value)}
                        placeholder="搜索关键词..."
                        className="h-7 text-xs max-w-[200px]"
                      />
                      <div className="max-h-48 overflow-y-auto rounded border border-slate-100 divide-y divide-slate-100">
                        {kwFilteredDefaults.map((e, i) => (
                          <div key={i} className="flex items-center gap-2 px-3 py-1 text-xs hover:bg-slate-50">
                            <span className="font-mono">{e.keyword}</span>
                            <span className="text-muted-foreground">→</span>
                            <span>{e.mapped}</span>
                          </div>
                        ))}
                        {kwFilteredDefaults.length === 0 && (
                          <p className="px-3 py-2 text-xs text-muted-foreground">无匹配结果</p>
                        )}
                      </div>
                    </div>
                  )}
                </div>

                {/* 重置 */}
                <div className="flex gap-2">
                  <Button size="sm" variant="outline" onClick={async () => {
                    setKeywordMaps({ ...keywordMaps, type_custom: [], sector_custom: [] })
                    try { await api.saveKeywordMaps("[]", "[]"); toast.success("已重置所有自定义关键词") } catch {}
                  }}>
                    <RotateCcw className="mr-1.5 h-3.5 w-3.5" /> 重置自定义
                  </Button>
                  <Button size="sm" variant="outline" onClick={handleResetSectors} disabled={resettingSectors}>
                    <RefreshCw className={cn("mr-1.5 h-3.5 w-3.5", resettingSectors && "animate-spin")} />
                    {resettingSectors ? "重置中..." : "重置板块映射"}
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}
        </TabsContent>
      </Tabs>
    </div>
  )
}
