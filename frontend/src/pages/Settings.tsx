import { useState, useEffect } from "react"
import { LineChart, Line, ResponsiveContainer } from "recharts"
import { getChannels, getChannelsAsync, saveChannels, getDefaultChannels } from "@/lib/channels"
import { getChannelColors, getChannelColorsAsync, saveChannelColors, getDefaultChannelColors, getPalette } from "@/lib/channelColors"
import { getColorTheme, getColorThemeAsync, saveColorTheme, applyColorTheme, type ColorTheme } from "@/lib/colorTheme"
import { formatRelativeTime, formatTokens } from "@/lib/format"
import PageHeader from "@/components/PageHeader"
import LoadingState from "@/components/LoadingState"
import EmptyState from "@/components/EmptyState"
import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import { clearToken } from "@/lib/auth"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Checkbox } from "@/components/ui/checkbox"
import { Select } from "@/components/ui/select"
import LogoSpinner from "@/components/LogoSpinner"
import ErrorState from "@/components/ErrorState"
import ThemeToggle from "@/components/ThemeToggle"
import { toast } from "sonner"
import { useLang, type Lang } from "@/i18n/LanguageContext"
import { cn } from "@/lib/utils"
import type { AIUsageStats, AIUsageDaily, AuditLog, KeywordMaps, KeywordEntry, SchedulerStatus, TpSlConfig, VisionConfig } from "@/api/types"
import {
  ChevronUp, ChevronDown, Plus, Trash2, RotateCcw,
  KeyRound, Bot, ShoppingCart, ShieldCheck, Save, RefreshCw,
  SlidersHorizontal, LogOut, Loader2, CheckCircle2, XCircle, Zap,
  Search, X, Palette, UserCircle, Clock, Archive, FileDown, Gift,
  Bell, TrendingUp, TrendingDown, Camera,
} from "lucide-react"

const PROVIDER_NAMES: Record<string, { zh: string; en: string }> = {
  kimi: { zh: "Kimi (月之暗面)", en: "Kimi (Moonshot)" },
  glm: { zh: "智谱 GLM", en: "Zhipu GLM" },
  qwen: { zh: "通义千问 (百炼)", en: "Qwen (Bailian)" },
  deepseek: { zh: "DeepSeek", en: "DeepSeek" },
  generic: { zh: "通用 OpenAI 兼容", en: "Generic OpenAI Compatible" },
}

function detectProvider(baseUrl: string, lang: Lang): string {
  const url = baseUrl.toLowerCase()
  let key = "generic"
  if (url.includes("moonshot") || url.includes("kimi")) key = "kimi"
  else if (url.includes("bigmodel") || url.includes("zhipu") || url.includes("glm")) key = "glm"
  else if (url.includes("dashscope") || url.includes("aliyun") || url.includes("aliyuncs") || url.includes("maas")) key = "qwen"
  else if (url.includes("deepseek")) key = "deepseek"
  return PROVIDER_NAMES[key][lang]
}

function Sparkline({ data }: { data: number[] }) {
  if (!data || data.length < 2) return null
  const chartData = data.map((v, i) => ({ i, v }))
  return (
    <ResponsiveContainer width="100%" height={40}>
      <LineChart data={chartData}>
        <Line type="monotone" dataKey="v" stroke="hsl(var(--primary))" strokeWidth={1.5} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  )
}

function AuditLogPanel() {
  const { t } = useLang()
  const { data: logs, loading, error, reload } = useApi<AuditLog[]>(() => api.getAuditLogs(100), [])

  const auditLabels: Record<string, string> = {
    login_success: t.settings.auditLabels.login_success,
    login_failed: t.settings.auditLabels.login_failed,
    change_password: t.settings.auditLabels.change_password,
    change_username: t.settings.auditLabels.change_username,
    add_transaction: t.settings.auditLabels.add_transaction,
    update_transaction: t.settings.auditLabels.update_transaction,
    delete_transaction: t.settings.auditLabels.delete_transaction,
    delete_all_transactions: t.settings.auditLabels.delete_all_transactions,
    clear_then_import: t.settings.auditLabels.clear_then_import,
    csv_import: t.settings.auditLabels.csv_import,
    update_ai_config: t.settings.auditLabels.update_ai_config,
    scheduler_toggle: t.settings.auditLabels.scheduler_toggle,
    scheduler_cron_change: t.settings.auditLabels.scheduler_cron_change,
    t1_nav_fix: t.settings.auditLabels.t1_nav_fix,
    nav_backfill: t.settings.auditLabels.nav_backfill,
    auto_invest_plan_create: t.settings.auditLabels.auto_invest_plan_create,
    auto_invest_plan_update: t.settings.auditLabels.auto_invest_plan_update,
    auto_invest_plan_delete: t.settings.auditLabels.auto_invest_plan_delete,
    auto_invest_plan_toggle: t.settings.auditLabels.auto_invest_plan_toggle,
    auto_invest_execute: t.settings.auditLabels.auto_invest_execute,
    watchlist_add: t.settings.auditLabels.watchlist_add,
    watchlist_group: t.settings.auditLabels.watchlist_group,
    watchlist_remove: t.settings.auditLabels.watchlist_remove,
    export_backup: t.settings.auditLabels.export_backup,
    update_dividend_method: t.settings.auditLabels.update_dividend_method,
    dividend_check: t.settings.auditLabels.dividend_check,
    dividend_scan: t.settings.auditLabels.dividend_scan,
    dividend_alert_update: t.settings.auditLabels.dividend_alert_update,
    dividend_alert_delete: t.settings.auditLabels.dividend_alert_delete,
    dividend_auto_check_toggle: t.settings.auditLabels.dividend_auto_check_toggle,
    tp_sl_config_update: t.settings.auditLabels.tp_sl_config_update,
    tp_sl_alert: t.settings.auditLabels.tp_sl_alert,
    tp_sl_alert_update: t.settings.auditLabels.tp_sl_alert_update,
  }

  return (
    <Card className="mt-4">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Clock className="h-5 w-5 text-primary" />
          {t.settings.auditLog}
        </CardTitle>
        <div className="flex items-center justify-between">
          <p className="text-sm text-muted-foreground">{t.settings.auditLogRecordsHint}</p>
          <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={reload} disabled={loading}>
            <RefreshCw className={cn("mr-1 h-3 w-3", loading && "animate-spin")} />
            {loading ? t.common.loading : t.common.refresh}
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {error ? (
          <div className="flex items-center gap-2 py-2">
            <span className="text-xs text-loss-600">{t.common.loadFailed}</span>
            <button onClick={reload} className="text-xs text-primary hover:underline">{t.common.retry}</button>
          </div>
        ) : !logs ? (
          <LoadingState size="sm" />
        ) : logs.length === 0 ? (
          <EmptyState title={t.settings.noAuditLogs} size="sm" />
        ) : (
          <div className="overflow-x-auto rounded-md border max-h-96 overflow-y-auto">
            <Table>
              <TableHeader className="sticky top-0 bg-background">
                <TableRow>
                  <TableHead className="text-xs">{t.settings.auditTime}</TableHead>
                  <TableHead className="text-xs">IP</TableHead>
                  <TableHead className="text-xs">{t.settings.auditUser}</TableHead>
                  <TableHead className="text-xs">{t.common.actions}</TableHead>
                  <TableHead className="text-xs">{t.settings.auditDetail}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {logs.map((log) => (
                  <TableRow key={log.id}>
                    <TableCell className="text-xs text-muted-foreground whitespace-nowrap tabular-nums">
                      {log.ts.slice(5, 19).replace("T", " ")}
                    </TableCell>
                    <TableCell className="text-xs font-mono">{log.ip || "—"}</TableCell>
                    <TableCell className="text-xs">{log.username || "—"}</TableCell>
                    <TableCell className="text-xs">{auditLabels[log.action] || log.action}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {log.detail ? (
                        <details className="group">
                          <summary className="cursor-pointer list-none max-w-[280px] truncate hover:text-foreground">
                            {log.detail}
                          </summary>
                          <pre className="mt-1 max-w-[400px] overflow-x-auto whitespace-pre-wrap break-all rounded bg-muted p-2 text-[10px] leading-relaxed">
                            {JSON.stringify(JSON.parse(log.detail), null, 2)}
                          </pre>
                        </details>
                      ) : "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

const PROVIDER_PRESETS = [
  { name: { zh: "智谱 GLM", en: "Zhipu GLM" }, baseUrl: "https://open.bigmodel.cn/v1", model: "glm-4-plus" },
  { name: { zh: "Kimi", en: "Kimi" }, baseUrl: "https://api.moonshot.cn/v1", model: "moonshot-v1-8k" },
  { name: { zh: "DeepSeek", en: "DeepSeek" }, baseUrl: "https://api.deepseek.com/v1", model: "deepseek-chat" },
  { name: { zh: "通义千问", en: "Qwen" }, baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1", model: "qwen-plus" },
]

const VISION_PRESETS = [
  { name: { zh: "智谱 GLM-4V", en: "Zhipu GLM-4V" }, baseUrl: "https://open.bigmodel.cn/v1", model: "glm-4v-plus", recommended: true },
  { name: { zh: "通义千问 VL", en: "Qwen VL" }, baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1", model: "qwen-vl-max" },
  { name: { zh: "OpenAI GPT-4o", en: "OpenAI GPT-4o" }, baseUrl: "https://api.openai.com/v1", model: "gpt-4o" },
  { name: { zh: "Kimi 视觉", en: "Kimi Vision" }, baseUrl: "https://api.moonshot.cn/v1", model: "moonshot-v1-8k-vision-preview" },
]

export default function Settings() {
  const { t, lang } = useLang()
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
  const { data: schedulerStatus, error: schedulerError, reload: reloadScheduler } = useApi<SchedulerStatus>(() => api.getSchedulerStatus(), [])
  const [schedulerToggling, setSchedulerToggling] = useState(false)
  const [cronTime, setCronTime] = useState("21:00")
  const [cronWeekdaysOnly, setCronWeekdaysOnly] = useState(true)
  const [cronSaving, setCronSaving] = useState(false)

  // TP/SL Alerts config
  const { data: tpSlConfig, reload: reloadTpSlConfig } = useApi<TpSlConfig>(() => api.getTpSlConfig(), [])
  const [tpSlEnabled, setTpSlEnabled] = useState(false)
  const [tpSlTakeProfitEnabled, setTpSlTakeProfitEnabled] = useState(true)
  const [tpSlStopLossEnabled, setTpSlStopLossEnabled] = useState(true)
  const [tpSlTakeProfit, setTpSlTakeProfit] = useState("20")
  const [tpSlStopLoss, setTpSlStopLoss] = useState("15")
  const [tpSlResetRatio, setTpSlResetRatio] = useState("80")
  const [tpSlSaving, setTpSlSaving] = useState(false)

  useEffect(() => {
    if (tpSlConfig) {
      setTpSlEnabled(tpSlConfig.enabled === "true")
      setTpSlTakeProfitEnabled(tpSlConfig.take_profit_enabled === "true")
      setTpSlStopLossEnabled(tpSlConfig.stop_loss_enabled === "true")
      setTpSlTakeProfit(String(Math.round(parseFloat(tpSlConfig.take_profit) * 100)))
      setTpSlStopLoss(String(Math.abs(Math.round(parseFloat(tpSlConfig.stop_loss) * 100))))
      setTpSlResetRatio(String(Math.round(parseFloat(tpSlConfig.reset_ratio) * 100)))
    }
  }, [tpSlConfig])

  const handleSaveTpSlConfig = async () => {
    setTpSlSaving(true)
    try {
      const tp = parseFloat(tpSlTakeProfit) / 100
      const sl = -parseFloat(tpSlStopLoss) / 100
      const rr = parseFloat(tpSlResetRatio) / 100
      if (Number.isNaN(tp) || Number.isNaN(sl) || Number.isNaN(rr)) {
        toast.error(t.settings.invalidNumber)
        setTpSlSaving(false)
        return
      }
      await api.updateTpSlConfig({
        enabled: String(tpSlEnabled),
        take_profit_enabled: String(tpSlTakeProfitEnabled),
        stop_loss_enabled: String(tpSlStopLossEnabled),
        take_profit: String(tp),
        stop_loss: String(sl),
        reset_ratio: String(rr),
      })
      reloadTpSlConfig()
      toast.success(t.settings.tpSlConfigSaved)
    } catch (e) { toast.error(`${t.common.saveFailed}: ${e}`) }
    finally { setTpSlSaving(false) }
  }

  const handleTpSlToggle = async () => {
    const next = !tpSlEnabled
    setTpSlEnabled(next)
    setTpSlSaving(true)
    try {
      await api.updateTpSlConfig({ enabled: String(next) })
      reloadTpSlConfig()
      toast.success(next ? t.settings.enabled : t.settings.paused)
    } catch (e) {
      setTpSlEnabled(!next)
      toast.error(`${t.common.operationFailed}: ${e}`)
    } finally { setTpSlSaving(false) }
  }

  useEffect(() => {
    if (schedulerStatus?.cron) {
      const parts = schedulerStatus.cron.split(/\s+/)
      if (parts.length === 5) {
        const h = parts[1].padStart(2, "0")
        const m = parts[0].padStart(2, "0")
        setCronTime(`${h}:${m}`)
        setCronWeekdaysOnly(parts[4] === "1-5")
      }
    }
  }, [schedulerStatus?.cron])

  const handleCronSave = async () => {
    const [h, m] = cronTime.split(":")
    if (h == null || m == null) { toast.warning(t.settings.invalidTimeFormat); return }
    const cron = `${parseInt(m)} ${parseInt(h)} * * ${cronWeekdaysOnly ? "1-5" : "*"}`
    setCronSaving(true)
    try {
      await api.setSchedulerCron(cron)
      toast.success(t.settings.scheduleTimeUpdated)
      reloadScheduler()
    } catch (e) { toast.error(`${t.common.saveFailed}: ${e}`) }
    finally { setCronSaving(false) }
  }

  // 页面加载时尝试从服务端同步渠道设置
  useEffect(() => {
    getChannelsAsync().then(setChannels).catch(() => {})
    getChannelColorsAsync().then(setChannelColors).catch(() => {})
    getColorThemeAsync().then((t) => { setColorTheme(t); applyColorTheme(t) }).catch(() => {})
  }, [])

  // Auth
  const { data: authStatus } = useApi(() => api.getAuthStatus(), [])
  const { data: authMe } = useApi(() => api.getMe(), [])
  const [currentPwd, setCurrentPwd] = useState("")
  const [newPwd, setNewPwd] = useState("")
  const [confirmPwd, setConfirmPwd] = useState("")
  const [changingPwd, setChangingPwd] = useState(false)
  const [newUsername, setNewUsername] = useState("")
  const [usernamePwd, setUsernamePwd] = useState("")
  const [changingUsername, setChangingUsername] = useState(false)

  // AI config
  const { data: aiConfig, error: aiConfigError, reload: reloadAIConfig } = useApi(() => api.getAIConfig(), [])
  const [aiBaseUrl, setAiBaseUrl] = useState("")
  const [aiApiKey, setAiApiKey] = useState("")
  const [aiModel, setAiModel] = useState("")
  const [aiWebSearch, setAiWebSearch] = useState(true)
  const [aiCustomPrompt, setAiCustomPrompt] = useState("")
  const [savingAI, setSavingAI] = useState(false)
  const [resettingSectors, setResettingSectors] = useState(false)

  // AI test connection
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; provider?: string; model?: string; has_search?: boolean; error?: string } | null>(null)

  // Vision model config (screenshot import)
  const { data: visionConfig, reload: reloadVisionConfig } = useApi<VisionConfig>(() => api.getVisionConfig(), [])
  const [visionBaseUrl, setVisionBaseUrl] = useState("")
  const [visionApiKey, setVisionApiKey] = useState("")
  const [visionModel, setVisionModel] = useState("")
  const [savingVision, setSavingVision] = useState(false)
  const [testingVision, setTestingVision] = useState(false)
  const [visionTestResult, setVisionTestResult] = useState<{ ok: boolean; model?: string; error?: string } | null>(null)

  // AI usage
  const { data: usageStats } = useApi<AIUsageStats>(() => api.getAIUsage(), [])
  const { data: usageDaily } = useApi<AIUsageDaily[]>(() => api.getAIUsageDaily(7), [])

  useEffect(() => {
    if (aiConfig) {
      setAiBaseUrl(aiConfig.base_url)
      setAiModel(aiConfig.model)
      setAiWebSearch(aiConfig.web_search)
      setAiCustomPrompt(aiConfig.custom_prompt || "")
    }
  }, [aiConfig])

  // Vision config sync
  useEffect(() => {
    if (visionConfig) {
      setVisionBaseUrl(visionConfig.base_url)
      setVisionModel(visionConfig.model)
    }
  }, [visionConfig])

  // Clear test results when config changes
  useEffect(() => { setTestResult(null) }, [aiBaseUrl, aiApiKey, aiModel, aiWebSearch, aiCustomPrompt])
  useEffect(() => { setVisionTestResult(null) }, [visionBaseUrl, visionApiKey, visionModel])

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
    if (channels.includes(name)) { toast.warning(t.settings.channelExists); return }
    const next = [...channels, name]
    setChannels(next); setNewChannel(""); await saveChannels(next)
  }
  const handleReset = async () => {
    const defaults = getDefaultChannels()
    setChannels(defaults); await saveChannels(defaults)
    toast.success(t.settings.channelsReset)
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
    toast.success(t.settings.channelColorsReset)
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
      toast.success(schedulerStatus.enabled ? t.settings.schedulePaused : t.settings.scheduleResumed)
    } catch (e) { toast.error(`${t.common.operationFailed}: ${e}`) }
    finally { setSchedulerToggling(false) }
  }

  const handleDividendToggle = async () => {
    if (!schedulerStatus) return
    setSchedulerToggling(true)
    try {
      await api.toggleDividendAutoCheck(!schedulerStatus.dividend_enabled)
      await reloadScheduler()
      toast.success(schedulerStatus.dividend_enabled ? t.settings.dividendAutoCheckOff : t.settings.dividendAutoCheckOn)
    } catch (e) { toast.error(`${t.common.operationFailed}: ${e}`) }
    finally { setSchedulerToggling(false) }
  }

  // --- Password ---
  const handleChangePassword = async () => {
    if (!currentPwd) { toast.error(t.settings.currentPasswordRequired); return }
    if (newPwd.length < 6) { toast.error(t.settings.passwordTooShort); return }
    if (newPwd !== confirmPwd) { toast.error(t.settings.passwordMismatch); return }
    setChangingPwd(true)
    try {
      await api.changePassword(currentPwd, newPwd)
      toast.success(t.settings.passwordChanged)
      setTimeout(() => { clearToken(); window.location.reload() }, 1500)
    } catch (e) { toast.error(`${t.settings.changeFailed}: ${e}`) }
    finally { setChangingPwd(false) }
  }

  const handleChangeUsername = async () => {
    if (newUsername.trim().length < 2) { toast.error(t.settings.usernameTooShort); return }
    if (!usernamePwd) { toast.error(t.settings.currentPasswordRequired); return }
    setChangingUsername(true)
    try {
      await api.changeUsername(usernamePwd, newUsername.trim())
      toast.success(t.settings.usernameChanged)
      setTimeout(() => { clearToken(); window.location.reload() }, 1500)
    } catch (e) { toast.error(`${t.settings.changeFailed}: ${e}`) }
    finally { setChangingUsername(false) }
  }

  // --- AI config ---
  const handleSaveAI = async () => {
    if (!aiBaseUrl.trim() || !aiModel.trim()) { toast.error(t.settings.aiConfigRequired); return }
    setSavingAI(true)
    try {
      await api.updateAIConfig(aiBaseUrl.trim(), aiApiKey, aiModel.trim(), aiWebSearch, aiCustomPrompt.trim().slice(0, 1000))
      setAiApiKey("")
      reloadAIConfig()
      toast.success(t.settings.aiConfigSaved)
    } catch (e) { toast.error(`${t.common.saveFailed}: ${e}`) }
    finally { setSavingAI(false) }
  }

  const handleTestConnection = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const res = await api.testAIConnection()
      setTestResult(res)
      if (res.ok) toast.success(`${t.settings.connectionSuccess} · ${res.provider} · ${res.model}`)
      else toast.error(`${t.settings.connectionFailed}: ${res.error}`)
    } catch (e) {
      toast.error(`${t.settings.testFailed}: ${e}`)
    } finally {
      setTesting(false)
    }
  }

  const handleSaveVision = async () => {
    if (!visionBaseUrl.trim() || !visionModel.trim()) { toast.error(t.settings.aiConfigRequired); return }
    setSavingVision(true)
    try {
      await api.updateVisionConfig(visionBaseUrl.trim(), visionApiKey, visionModel.trim())
      setVisionApiKey("")
      reloadVisionConfig()
      toast.success(t.settings.visionConfigSaved)
    } catch (e) { toast.error(`${t.common.saveFailed}: ${e}`) }
    finally { setSavingVision(false) }
  }

  const handleTestVision = async () => {
    setTestingVision(true)
    setVisionTestResult(null)
    try {
      const res = await api.testVision()
      setVisionTestResult(res)
      if (res.ok) toast.success(`${t.settings.visionTestOk} · ${res.model}`)
      else toast.error(`${t.settings.visionTestFail}`.replace("{error}", res.error || ""))
    } catch (e) {
      toast.error(`${t.settings.testFailed}: ${e}`)
    } finally {
      setTestingVision(false)
    }
  }

  const handleResetSectors = async () => {
    setResettingSectors(true)
    try {
      const res = await api.resetSectors()
      toast.success(t.settings.sectorsReset.replace("{n}", String(res.reset)))
    } catch (e) { toast.error(`${t.settings.resetFailed}: ${e}`) }
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
    if (!keyword || !mapped) { toast.warning(t.settings.kwKeywordMappedRequired); return }
    if (kwCustom.some((e) => e.keyword === keyword)) { toast.warning(t.settings.kwKeywordExists); return }
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
    try { await api.saveKeywordMaps(JSON.stringify(typeCustom), JSON.stringify(sectorCustom)); toast.success(t.settings.kwCustomReset) } catch {}
  }

  const authRequired = authStatus?.required

  return (
    <div className="space-y-6">
      <PageHeader title={t.settings.title} tracking="tight" />

      <Tabs defaultValue="ai">
        <TabsList className={cn("grid w-full sm:inline-flex sm:w-auto", authRequired ? "grid-cols-3" : "grid-cols-2")}>
          {authRequired && (
            <TabsTrigger value="account" className="gap-1.5">
              <ShieldCheck className="h-4 w-4" />
              <span className="hidden sm:inline">{t.settings.accountSecurity}</span><span className="sm:hidden">{t.settings.account}</span>
            </TabsTrigger>
          )}
          <TabsTrigger value="ai" className="gap-1.5">
            <Bot className="h-4 w-4" />
            <span className="hidden sm:inline">{t.settings.aiAdvisor}</span><span className="sm:hidden">{t.settings.ai}</span>
          </TabsTrigger>
          <TabsTrigger value="prefs" className="gap-1.5">
            <SlidersHorizontal className="h-4 w-4" />
            <span className="hidden sm:inline">{t.settings.preferences}</span><span className="sm:hidden">{t.settings.prefs}</span>
          </TabsTrigger>
        </TabsList>

        {/* ── 账户与安全 ── */}
        {authRequired && (
          <TabsContent value="account">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="flex items-center gap-2 text-base">
                  <ShieldCheck className="h-5 w-5 text-primary" />
                  {t.settings.accountSecurity}
                </CardTitle>
                <p className="text-sm text-muted-foreground">
                  {t.settings.currentUsername}<span className="font-medium text-foreground">{authMe?.username || "—"}</span>
                </p>
              </CardHeader>
            <CardContent className="space-y-5">
              {aiConfigError && (
                <div className="flex items-center gap-2 rounded-md border border-loss-200 bg-loss-50 px-3 py-2 text-xs">
                  <span className="text-loss-700">{t.settings.aiConfigLoadFailed}</span>
                  <button
                    onClick={reloadAIConfig}
                    className="text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]"
                  >
                    {t.common.retry}
                  </button>
                </div>
              )}
                {/* 修改用户名 */}
                <div className="space-y-2">
                  <Label className="text-xs font-medium text-muted-foreground">{t.settings.changeUsername}</Label>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <Input value={newUsername} onChange={(e) => setNewUsername(e.target.value)}
                      className="h-8 text-xs" placeholder={t.settings.newUsernamePlaceholder} />
                    <Input type="password" value={usernamePwd} onChange={(e) => setUsernamePwd(e.target.value)}
                      className="h-8 text-xs" placeholder={t.settings.currentPassword}
                      onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); handleChangeUsername() } }} />
                  </div>
                  <Button size="sm" onClick={handleChangeUsername} disabled={changingUsername} variant="outline">
                    <UserCircle className="mr-1.5 h-3.5 w-3.5" /> {changingUsername ? t.settings.changing : t.settings.changeUsername}
                  </Button>
                </div>

                <div className="border-t pt-4" />

                {/* 修改密码 */}
                <div className="space-y-2">
                  <Label className="text-xs font-medium text-muted-foreground">{t.settings.changePassword}</Label>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <div>
                      <Label className="mb-1 block text-xs text-muted-foreground">{t.settings.currentPassword}</Label>
                      <Input type="password" value={currentPwd} onChange={(e) => setCurrentPwd(e.target.value)}
                        className="h-8 text-xs" placeholder={t.settings.currentPasswordPlaceholder} />
                    </div>
                    <div>
                      <Label className="mb-1 block text-xs text-muted-foreground">{t.settings.newPassword}</Label>
                      <Input type="password" value={newPwd} onChange={(e) => setNewPwd(e.target.value)}
                        className="h-8 text-xs" placeholder={t.settings.passwordMinHint} />
                    </div>
                    <div>
                      <Label className="mb-1 block text-xs text-muted-foreground">{t.settings.confirmNewPassword}</Label>
                      <Input type="password" value={confirmPwd} onChange={(e) => setConfirmPwd(e.target.value)}
                        className="h-8 text-xs" placeholder={t.settings.confirmPasswordPlaceholder}
                        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); handleChangePassword() } }} />
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" onClick={handleChangePassword} disabled={changingPwd} variant="outline">
                      <KeyRound className="mr-1.5 h-3.5 w-3.5" /> {changingPwd ? t.settings.changing : t.settings.changePassword}
                    </Button>
                    <Button size="sm" variant="outline" className="text-destructive hover:bg-destructive/10 hover:text-destructive"
                      onClick={() => { clearToken(); window.location.reload() }}>
                      <LogOut className="mr-1.5 h-3.5 w-3.5" /> {t.settings.logout}
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* ── 审计日志 ── */}
            <AuditLogPanel />
          </TabsContent>
        )}

        {/* ── AI 投顾 ── */}
        <TabsContent value="ai">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <Bot className="h-5 w-5 text-primary" />
                {t.settings.aiAdvisorConfig}
              </CardTitle>
              <p className="text-sm text-muted-foreground">{t.settings.aiConfigHint}</p>
            </CardHeader>
            <CardContent className="space-y-5">
              {/* API 配置 */}
              <div className="space-y-3">
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  <div>
                    <Label className="mb-1 block text-xs text-muted-foreground">{t.settings.aiBaseUrl}</Label>
                    <Input value={aiBaseUrl} onChange={(e) => setAiBaseUrl(e.target.value)}
                      className="h-8 text-xs" placeholder="https://api.moonshot.cn/v1" />
                  </div>
                  <div>
                    <Label className="mb-1 block text-xs text-muted-foreground">{t.settings.aiApiKey}</Label>
                    <Input type="password" value={aiApiKey} onChange={(e) => setAiApiKey(e.target.value)}
                      className="h-8 text-xs"
                      placeholder={aiConfig?.has_key ? t.settings.apiKeyConfigured : "sk-..."} />
                  </div>
                  <div>
                    <Label className="mb-1 block text-xs text-muted-foreground">{t.settings.aiModel}</Label>
                    <Input value={aiModel} onChange={(e) => setAiModel(e.target.value)}
                      className="h-8 text-xs" placeholder="glm-4-plus / moonshot-v1-8k / deepseek-chat" />
                  </div>
                </div>

                {/* 平台快捷预设 */}
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs text-muted-foreground">{t.settings.quickFill}</span>
                  {PROVIDER_PRESETS.map((p) => (
                    <button
                      key={p.name.zh}
                      type="button"
                      onClick={() => { setAiBaseUrl(p.baseUrl); setAiModel(p.model) }}
                      className="rounded-full border border-border bg-background px-2.5 py-0.5 text-xs text-muted-foreground transition-colors hover:border-primary/30 hover:bg-primary/10 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]"
                    >
                      {p.name[lang]}
                    </button>
                  ))}
                </div>

                {/* 联网搜索 */}
                <div className="flex flex-wrap items-center gap-3">
                  <label className="flex items-center gap-1.5 text-xs cursor-pointer select-none">
                    <Checkbox checked={aiWebSearch} onCheckedChange={(v) => setAiWebSearch(!!v)} />
                    {t.settings.enableWebSearch}
                  </label>
                  {aiWebSearch && aiBaseUrl && (
                    <span className="text-xs text-primary bg-primary/10 px-2 py-0.5 rounded-full">
                      {detectProvider(aiBaseUrl, lang)}
                    </span>
                  )}
                </div>

                {/* 浅色分隔线 — 技术配置 / 个性化指令 */}
                <div className="border-t border-border/40" />

                {/* 自定义指令 */}
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <Label className="text-xs text-muted-foreground">{t.settings.customPrompt}</Label>
                    <span className="text-[10px] text-muted-foreground/50">{aiCustomPrompt.length}/1000</span>
                  </div>
                  <textarea
                    value={aiCustomPrompt}
                    onChange={(e) => setAiCustomPrompt(e.target.value.slice(0, 1000))}
                    rows={4}
                    placeholder={t.settings.customPromptPlaceholder}
                    className="w-full resize-y rounded-md border border-border bg-background px-3 py-2 text-xs leading-relaxed outline-none focus:ring-2 focus:ring-ring focus:ring-offset-1 placeholder:text-muted-foreground/50"
                  />
                  <p className="text-[10px] text-muted-foreground/60">{t.settings.customPromptHint}</p>
                </div>

                {/* 操作按钮 */}
                <div className="flex flex-wrap items-center gap-2">
                  <Button size="sm" onClick={handleSaveAI} disabled={savingAI}>
                    <Save className="mr-1.5 h-3.5 w-3.5" /> {savingAI ? t.settings.saving : t.settings.saveConfig}
                  </Button>
                  <Button size="sm" variant="outline" onClick={handleTestConnection} disabled={testing}>
                    {testing ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Zap className="mr-1.5 h-3.5 w-3.5" />}
                    {testing ? t.settings.testing : t.settings.testConnection}
                  </Button>
                </div>

                {/* 测试结果 */}
                {testResult && (
                  <div className={cn(
                    "flex items-center gap-1.5 rounded-md px-3 py-2 text-xs",
                    testResult.ok ? "bg-success/10 text-success border border-success/30" : "bg-destructive/10 text-destructive border border-destructive/30"
                  )}>
                    {testResult.ok
                      ? <><CheckCircle2 className="h-3.5 w-3.5 shrink-0" /> {t.settings.connectionSuccess} · {testResult.provider} · {testResult.model}{testResult.has_search ? ` · ${t.settings.webSearchEnabled}` : ""}</>
                      : <><XCircle className="h-3.5 w-3.5 shrink-0" /> {testResult.error}</>
                    }
                  </div>
                )}
              </div>

              {/* 分隔线 — AI 配置 / 视觉模型 */}
              <div className="border-t border-border/60" />

              {/* 视觉模型配置（截图导入） */}
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <Camera className="h-4 w-4 text-primary" />
                  <p className="text-sm font-medium">{t.settings.visionModel}</p>
                </div>
                <p className="text-xs text-muted-foreground -mt-2">{t.settings.visionModelHint}</p>

                {/* API 配置 */}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                  <div>
                    <Label className="mb-1 block text-xs text-muted-foreground">{t.settings.aiBaseUrl}</Label>
                    <Input value={visionBaseUrl} onChange={(e) => setVisionBaseUrl(e.target.value)}
                      className="h-8 text-xs" placeholder="https://open.bigmodel.cn/v1" />
                  </div>
                  <div>
                    <Label className="mb-1 block text-xs text-muted-foreground">{t.settings.aiApiKey}</Label>
                    <Input type="password" value={visionApiKey} onChange={(e) => setVisionApiKey(e.target.value)}
                      className="h-8 text-xs"
                      placeholder={visionConfig?.has_key ? t.settings.apiKeyConfigured : "sk-..."} />
                  </div>
                  <div>
                    <Label className="mb-1 block text-xs text-muted-foreground">{t.settings.aiModel}</Label>
                    <Input value={visionModel} onChange={(e) => setVisionModel(e.target.value)}
                      className="h-8 text-xs" placeholder={t.settings.visionModelPlaceholder} />
                  </div>
                </div>

                {/* 平台快捷预设 */}
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs text-muted-foreground">{t.settings.quickFill}</span>
                  {VISION_PRESETS.map((p) => (
                    <button
                      key={p.name.zh}
                      type="button"
                      onClick={() => { setVisionBaseUrl(p.baseUrl); setVisionModel(p.model) }}
                      className="rounded-full border border-border bg-background px-2.5 py-0.5 text-xs text-muted-foreground transition-colors hover:border-primary/30 hover:bg-primary/10 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]"
                    >
                      {p.name[lang]}{p.recommended ? ` · ${t.settings.visionRecommended}` : ""}
                    </button>
                  ))}
                </div>

                {/* 操作按钮 */}
                <div className="flex flex-wrap items-center gap-2">
                  <Button size="sm" onClick={handleSaveVision} disabled={savingVision}>
                    <Save className="mr-1.5 h-3.5 w-3.5" /> {savingVision ? t.settings.saving : t.settings.saveConfig}
                  </Button>
                  <Button size="sm" variant="outline" onClick={handleTestVision} disabled={testingVision}>
                    {testingVision ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Zap className="mr-1.5 h-3.5 w-3.5" />}
                    {testingVision ? t.settings.visionTesting : t.settings.testConnection}
                  </Button>
                </div>

                {/* 测试结果 */}
                {visionTestResult && (
                  <div className={cn(
                    "flex items-center gap-1.5 rounded-md px-3 py-2 text-xs",
                    visionTestResult.ok ? "bg-success/10 text-success border border-success/30" : "bg-destructive/10 text-destructive border border-destructive/30"
                  )}>
                    {visionTestResult.ok
                      ? <><CheckCircle2 className="h-3.5 w-3.5 shrink-0" /> {t.settings.visionTestOk} · {visionTestResult.model}</>
                      : <><XCircle className="h-3.5 w-3.5 shrink-0" /> {visionTestResult.error}</>
                    }
                  </div>
                )}
              </div>

              {/* 分隔线 — 视觉模型 / Token 用量 */}
              <div className="border-t border-border/60" />

              {/* Token 用量 */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium">{t.aiChat.tokenUsed}</p>
                  {usageStats && (
                    <p className="text-xs text-muted-foreground">
                      {t.aiChat.todayLabel} <span className="font-medium text-foreground">{formatTokens(usageStats.today)}</span>
                      {" · "}{t.aiChat.totalLabel} <span className="font-medium text-foreground">{formatTokens(usageStats.total)}</span>
                    </p>
                  )}
                </div>

                {/* 7 天趋势 sparkline */}
                {usageDaily && usageDaily.length >= 2 ? (
                  <div className="rounded-lg border bg-muted/50 px-3 py-2">
                    <Sparkline data={usageDaily.map((d) => d.tokens)} />
                    <div className="flex justify-between text-[10px] text-muted-foreground mt-0.5">
                      <span>{usageDaily[0].date.slice(5)}</span>
                      <span>{t.settings.last7Days}</span>
                      <span>{usageDaily[usageDaily.length - 1].date.slice(5)}</span>
                    </div>
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground py-2">{t.settings.noUsageData}</p>
                )}

                {/* 最近调用表格 */}
                {usageStats && usageStats.recent.length > 0 ? (
                  <div className="overflow-x-auto rounded-md border">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className="text-xs">{t.settings.auditTime}</TableHead>
                          <TableHead className="text-xs">{t.settings.aiModel}</TableHead>
                          <TableHead className="text-xs text-right">{t.aiChat.inputLabel}</TableHead>
                          <TableHead className="text-xs text-right">{t.aiChat.outputLabel}</TableHead>
                          <TableHead className="text-xs text-right">{t.common.total}</TableHead>
                          <TableHead className="text-xs text-right">{t.aiChat.turnsUnit}</TableHead>
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
                  !usageStats && <LoadingState size="sm" />
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ── 偏好设置 ── */}
        <TabsContent value="prefs" className="space-y-4">
          {/* 渠道管理 */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <ShoppingCart className="h-5 w-5 text-primary" />
                {t.settings.channelManagement}
              </CardTitle>
              <p className="text-sm text-muted-foreground">{t.settings.channelMgmtHint}</p>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1">
                {channels.map((ch, i) => (
                  <div key={ch} className="flex flex-col gap-2 rounded-lg px-3 py-2 transition-colors hover:bg-muted/40 sm:flex-row sm:items-center sm:gap-2">
                    <div className="flex flex-1 items-center gap-2">
                      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-muted text-xs font-medium text-muted-foreground">
                        {i + 1}
                      </span>
                      <span className="flex-1 text-sm font-semibold">{ch}</span>
                      {i === 0 && <span className="text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded">{t.settings.defaultLabel}</span>}
                      <button onClick={() => remove(i)}
                        className="flex h-7 w-7 items-center justify-center rounded text-muted-foreground/70 transition-colors hover:bg-destructive/10 hover:text-destructive focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98] sm:h-6 sm:w-6">
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <button onClick={() => moveUp(i)} disabled={i === 0}
                        className="flex h-7 w-7 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:opacity-20 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98] sm:h-5 sm:w-5">
                        <ChevronUp className="h-3.5 w-3.5" />
                      </button>
                      <button onClick={() => moveDown(i)} disabled={i === channels.length - 1}
                        className="flex h-7 w-7 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:opacity-20 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98] sm:h-5 sm:w-5">
                        <ChevronDown className="h-3.5 w-3.5" />
                      </button>
                      <div className="flex flex-wrap items-center gap-1">
                        {palette.map(color => (
                          <button key={color} onClick={() => handleColorChange(ch, color)}
                            className={cn("h-6 w-6 rounded-full border-2 transition-transform hover:scale-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]",
                              channelColors[ch] === color ? "border-border" : "border-transparent")}
                            style={{ background: color }} />
                        ))}
                      </div>
                      <input type="color" value={channelColors[ch] ?? "#3b82f6"}
                        onChange={(e) => handleColorChange(ch, e.target.value)}
                        className="h-7 w-7 rounded cursor-pointer border border-border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2" />
                    </div>
                  </div>
                ))}
              </div>

              <div className="flex flex-wrap gap-2">
                <div className="flex flex-1 gap-2 min-w-0">
                  <Input
                    value={newChannel}
                    onChange={(e) => setNewChannel(e.target.value)}
                    placeholder={t.settings.newChannelPlaceholder}
                    onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add() } }}
                    className="h-8 text-xs max-w-[180px]"
                  />
                  <Button variant="outline" size="sm" onClick={add} className="h-8 shrink-0">
                    <Plus className="mr-1 h-3.5 w-3.5" /> {t.common.add}
                  </Button>
                </div>
                <Button variant="outline" size="sm" onClick={() => { handleReset(); handleColorsReset() }} className="h-8 shrink-0">
                  <RotateCcw className="mr-1 h-3.5 w-3.5" /> {t.settings.restoreDefaults}
                </Button>
              </div>
            </CardContent>
          </Card>

          {/* 显示设置 */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <Palette className="h-5 w-5 text-primary" />
                {t.settings.displaySettings}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <p className="text-sm font-semibold">{t.settings.upDownColor}</p>
                <div className="flex gap-2">
                  <button
                    onClick={() => handleThemeChange("international")}
                    disabled={colorThemeLoading}
                    className={cn(
                      "flex-1 rounded-lg border px-3 py-2.5 text-sm transition-colors disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]",
                      colorTheme === "international"
                        ? "border-primary/30 bg-primary/10 text-primary"
                        : "border-border bg-background text-muted-foreground hover:bg-accent"
                    )}
                  >
                    <span className="text-success font-semibold">▲</span> {t.settings.greenUp}
                    <span className="text-destructive font-semibold ml-2">▼</span> {t.settings.redDown}
                    <span className="block text-[11px] text-muted-foreground mt-0.5">{t.settings.internationalConvention}</span>
                  </button>
                  <button
                    onClick={() => handleThemeChange("china")}
                    disabled={colorThemeLoading}
                    className={cn(
                      "flex-1 rounded-lg border px-3 py-2.5 text-sm transition-colors disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]",
                      colorTheme === "china"
                        ? "border-primary/30 bg-primary/10 text-primary"
                        : "border-border bg-background text-muted-foreground hover:bg-accent"
                    )}
                  >
                    <span className="text-destructive font-semibold">▲</span> {t.settings.redUp}
                    <span className="text-success font-semibold ml-2">▼</span> {t.settings.greenDown}
                    <span className="block text-[11px] text-muted-foreground mt-0.5">{t.settings.chinaConvention}</span>
                  </button>
                </div>
              </div>
              <div className="space-y-2">
                <p className="text-sm font-semibold">{t.settings.appearanceTheme}</p>
                <ThemeToggle variant="segmented" className="w-full" />
                <p className="text-xs text-muted-foreground">{t.settings.themeHint}</p>
              </div>
            </CardContent>
          </Card>

          {/* 定时净值更新 */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <Clock className="h-5 w-5 text-primary" />
                {t.settings.scheduledNavUpdate}
              </CardTitle>
              <p className="text-sm text-muted-foreground">{t.settings.autoFetchNav}</p>
            </CardHeader>
            <CardContent>
              {schedulerError ? (
                <div className="flex items-center gap-2 py-2">
                  <span className="text-xs text-loss-600">{t.common.loadFailed}</span>
                  <button
                    onClick={reloadScheduler}
                    className="text-xs text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]"
                  >
                    {t.common.retry}
                  </button>
                </div>
              ) : schedulerStatus ? (
                <div className="space-y-3">
                  <div className="flex items-center gap-2">
                    <button
                      onClick={handleSchedulerToggle}
                      disabled={schedulerToggling}
                      className={cn(
                        "rounded-lg border px-3 py-1.5 text-sm transition-colors disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]",
                        schedulerStatus.enabled
                          ? "border-primary/30 bg-primary/10 text-primary"
                          : "border-border bg-background text-muted-foreground hover:bg-accent"
                      )}
                    >
                      {schedulerToggling ? t.settings.switching : schedulerStatus.enabled ? t.settings.enabled : t.settings.paused}
                    </button>
                    <span className="text-xs text-muted-foreground font-mono">
                      cron: {schedulerStatus.cron}
                    </span>
                  </div>
                  <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
                    {schedulerStatus.next_run && (
                      <span>{t.settings.nextRun}<span className="font-semibold text-foreground">{schedulerStatus.next_run}</span></span>
                    )}
                    {schedulerStatus.last_run && (
                      <span>{t.settings.lastRun}<span className="font-semibold text-foreground">{schedulerStatus.last_run}</span></span>
                    )}
                    {schedulerStatus.last_results && schedulerStatus.last_results.length > 0 && (
                      <span>
                        {t.settings.lastResult}{" "}
                        <span className="text-gain-600 font-semibold">
                          {schedulerStatus.last_results.filter(r => r.ok).length} {t.common.success}
                        </span>
                        {" / "}
                        <span className="text-loss-600 font-semibold">
                          {schedulerStatus.last_results.filter(r => !r.ok).length} {t.common.failed}
                        </span>
                      </span>
                    )}
                  </div>
                  {/* 时间设置 */}
                  <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-border/60">
                    <span className="text-xs text-muted-foreground">{t.settings.scheduleTime}</span>
                    <input
                      type="time"
                      value={cronTime}
                      onChange={(e) => setCronTime(e.target.value)}
                      className="h-7 rounded-md border border-input bg-background px-2 text-xs tabular-nums focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                    />
                    <label className="flex items-center gap-1 text-xs text-muted-foreground cursor-pointer">
                      <Checkbox
                        checked={cronWeekdaysOnly}
                        onCheckedChange={(v) => setCronWeekdaysOnly(!!v)}
                      />
                      {t.settings.weekdaysOnly}
                    </label>
                    <Button size="sm" variant="outline" className="h-7 text-xs" onClick={handleCronSave} disabled={cronSaving}>
                      {cronSaving ? t.settings.saving : t.common.save}
                    </Button>
                  </div>
                </div>
              ) : (
                <LoadingState size="xs" />
              )}
            </CardContent>
          </Card>

          {/* 分红自动检测 */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <Gift className="h-5 w-5 text-primary" />
                {t.settings.dividendAutoCheck}
              </CardTitle>
              <p className="text-sm text-muted-foreground">{t.settings.dividendAutoCheckDesc}</p>
            </CardHeader>
            <CardContent>
              {schedulerStatus ? (
                <div className="space-y-2">
                  <div className="flex items-center gap-2">
                    <button
                      onClick={handleDividendToggle}
                      disabled={schedulerToggling}
                      className={cn(
                        "rounded-lg border px-3 py-1.5 text-sm transition-colors disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]",
                        schedulerStatus.dividend_enabled
                          ? "border-primary/30 bg-primary/10 text-primary"
                          : "border-border bg-background text-muted-foreground hover:bg-accent"
                      )}
                    >
                      {schedulerToggling ? t.settings.switching : schedulerStatus.dividend_enabled ? t.settings.enabled : t.settings.paused}
                    </button>
                    <span className="text-xs text-muted-foreground">09:30</span>
                  </div>
                  {schedulerStatus.dividend_last_run && (
                    <div className="text-xs text-muted-foreground">
                      {t.settings.lastRun}<span className="font-semibold text-foreground ml-1">{schedulerStatus.dividend_last_run}</span>
                    </div>
                  )}
                </div>
              ) : (
                <LoadingState size="xs" />
              )}
            </CardContent>
          </Card>

          {/* 止盈止损提醒 */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <Bell className="h-5 w-5 text-primary" />
                {t.settings.tpSlAlerts}
              </CardTitle>
              <p className="text-sm text-muted-foreground">{t.settings.tpSlAlertsDesc}</p>
            </CardHeader>
            <CardContent>
              {tpSlConfig ? (
                <div className="space-y-4">
                  <div className="flex items-center gap-2">
                    <button
                      onClick={handleTpSlToggle}
                      disabled={tpSlSaving}
                      className={cn(
                        "rounded-lg border px-3 py-1.5 text-sm transition-colors disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]",
                        tpSlEnabled
                          ? "border-primary/30 bg-primary/10 text-primary"
                          : "border-border bg-background text-muted-foreground hover:bg-accent"
                      )}
                    >
                      {tpSlSaving ? t.settings.switching : tpSlEnabled ? t.settings.enabled : t.settings.paused}
                    </button>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <div className="flex items-center gap-2">
                        <Checkbox
                          id="tp-take-profit-enabled"
                          checked={tpSlTakeProfitEnabled}
                          onCheckedChange={(v) => setTpSlTakeProfitEnabled(Boolean(v))}
                        />
                        <Label htmlFor="tp-take-profit-enabled" className="text-sm">{t.settings.takeProfitEnabled}</Label>
                        <TrendingUp className="h-4 w-4 text-gain-500" />
                      </div>
                      <div className="flex items-center gap-2">
                        <Input
                          type="number"
                          value={tpSlTakeProfit}
                          onChange={(e) => setTpSlTakeProfit(e.target.value)}
                          className="h-8 text-xs"
                        />
                        <span className="text-xs text-muted-foreground">%</span>
                      </div>
                    </div>
                    <div className="space-y-2">
                      <div className="flex items-center gap-2">
                        <Checkbox
                          id="tp-stop-loss-enabled"
                          checked={tpSlStopLossEnabled}
                          onCheckedChange={(v) => setTpSlStopLossEnabled(Boolean(v))}
                        />
                        <Label htmlFor="tp-stop-loss-enabled" className="text-sm">{t.settings.stopLossEnabled}</Label>
                        <TrendingDown className="h-4 w-4 text-loss-500" />
                      </div>
                      <div className="flex items-center gap-2">
                        <Input
                          type="number"
                          value={tpSlStopLoss}
                          onChange={(e) => setTpSlStopLoss(e.target.value)}
                          className="h-8 text-xs"
                        />
                        <span className="text-xs text-muted-foreground">%</span>
                      </div>
                    </div>
                  </div>
                  <div className="space-y-2">
                    <Label className="text-xs text-muted-foreground">{t.settings.resetRatio}</Label>
                    <div className="flex items-center gap-2">
                      <Input
                        type="number"
                        value={tpSlResetRatio}
                        onChange={(e) => setTpSlResetRatio(e.target.value)}
                        className="h-8 text-xs w-24"
                      />
                      <span className="text-xs text-muted-foreground">%</span>
                    </div>
                    <p className="text-xs text-muted-foreground">{t.settings.resetRatioDesc}</p>
                  </div>
                  <Button size="sm" onClick={handleSaveTpSlConfig} disabled={tpSlSaving}>
                    {tpSlSaving ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Save className="mr-1 h-4 w-4" />}
                    {t.common.save}
                  </Button>
                </div>
              ) : (
                <LoadingState size="xs" />
              )}
            </CardContent>
          </Card>

          {/* ── 关键词映射 ── */}
          {keywordMaps && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="flex items-center gap-2 text-base">
                  <Search className="h-5 w-5 text-primary" />
                  {t.settings.keywordMapping}
                </CardTitle>
                <p className="text-sm text-muted-foreground">{t.settings.keywordMappingHint}</p>
              </CardHeader>
              <CardContent className="space-y-4">
                {/* Tab: 板块 / 类型 */}
                <div className="flex gap-1 rounded-lg bg-muted p-1 w-fit">
                  {([["sector", t.settings.sectorKeywords], ["type", t.settings.typeKeywords]] as const).map(([key, label]) => (
                    <button
                      key={key}
                      type="button"
                      onClick={() => { setKwTab(key); setKwSearch("") }}
                      className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98] ${kwTab === key ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
                    >
                      {label}
                    </button>
                  ))}
                </div>

                {/* 添加自定义 */}
                <div className="flex flex-wrap items-end gap-2">
                  <div className="flex-1 min-w-0 sm:min-w-[120px]">
                    <Label className="mb-1 block text-xs text-muted-foreground">{t.settings.keyword}</Label>
                    <Input value={newKwKeyword} onChange={(e) => setNewKwKeyword(e.target.value)}
                      placeholder={t.settings.keywordPlaceholder} className="h-8 text-xs"
                      onKeyDown={(e) => { if (e.key === "Enter") addCustomKeyword() }} />
                  </div>
                  <div className="flex-1 min-w-0 sm:min-w-[120px]">
                    <Label className="mb-1 block text-xs text-muted-foreground">{t.settings.mapTo}</Label>
                    <Select
                      value={newKwMapped}
                      onChange={(e) => setNewKwMapped(e.target.value)}
                      className="h-8 text-xs shadow-sm"
                    >
                      <option value="">{t.settings.selectLabel}{kwTab === "sector" ? t.common.sector : t.common.type}</option>
                      {kwAvailable.map((a) => <option key={a} value={a}>{a}</option>)}
                    </Select>
                  </div>
                  <Button size="sm" onClick={addCustomKeyword} className="h-8 shrink-0">
                    <Plus className="mr-1 h-3.5 w-3.5" /> {t.common.add}
                  </Button>
                </div>

                {/* 自定义关键词列表 */}
                {kwCustom.length > 0 && (
                  <div className="space-y-1">
                    <p className="text-xs font-medium text-muted-foreground">{t.settings.customKeywordsCount.replace("{n}", String(kwCustom.length))}</p>
                    {kwCustom.map((e, i) => (
                      <div key={i} className="flex flex-col gap-1.5 rounded-lg border border-warning/30 bg-warning/10 px-3 py-1.5 sm:flex-row sm:items-center sm:gap-2">
                        <div className="flex items-center gap-1.5">
                          <button onClick={() => moveCustomKeyword(i, -1)} disabled={i === 0}
                            className="flex h-7 w-7 items-center justify-center rounded text-muted-foreground hover:bg-accent disabled:opacity-20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98] sm:h-5 sm:w-5">
                            <ChevronUp className="h-3 w-3" />
                          </button>
                          <button onClick={() => moveCustomKeyword(i, 1)} disabled={i === kwCustom.length - 1}
                            className="flex h-7 w-7 items-center justify-center rounded text-muted-foreground hover:bg-accent disabled:opacity-20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98] sm:h-5 sm:w-5">
                            <ChevronDown className="h-3 w-3" />
                          </button>
                        </div>
                        <span className="text-sm font-medium flex-1">{e.keyword}</span>
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-muted-foreground">→</span>
                          <span className="text-sm font-medium text-primary">{e.mapped}</span>
                          <button onClick={() => deleteCustomKeyword(i)}
                            className="flex h-7 w-7 items-center justify-center rounded text-muted-foreground/70 hover:text-destructive focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98] sm:h-5 sm:w-5">
                            <X className="h-3.5 w-3.5" />
                          </button>
                        </div>
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
                    {kwShowDefaults ? t.settings.collapse : t.settings.expand}{t.settings.defaultKeywordsCount.replace("{n}", String(kwDefaults.length))}
                  </button>
                  {kwShowDefaults && (
                    <div className="mt-2 space-y-2">
                      <Input
                        value={kwSearch}
                        onChange={(e) => setKwSearch(e.target.value)}
                        placeholder={t.settings.searchKeywordPlaceholder}
                        className="h-7 text-xs max-w-[200px]"
                      />
                      <div className="max-h-48 overflow-y-auto rounded border border-border/60 divide-y divide-border/60">
                        {kwFilteredDefaults.map((e, i) => (
                          <div key={i} className="flex items-center gap-2 px-3 py-1 text-xs hover:bg-accent">
                            <span className="font-mono">{e.keyword}</span>
                            <span className="text-muted-foreground">→</span>
                            <span>{e.mapped}</span>
                          </div>
                        ))}
                        {kwFilteredDefaults.length === 0 && (
                          <p className="px-3 py-2 text-xs text-muted-foreground">{t.common.noResults}</p>
                        )}
                      </div>
                    </div>
                  )}
                </div>

                {/* 重置 */}
                <div className="flex gap-2">
                  <Button size="sm" variant="outline" onClick={async () => {
                    setKeywordMaps({ ...keywordMaps, type_custom: [], sector_custom: [] })
                    try { await api.saveKeywordMaps("[]", "[]"); toast.success(t.settings.allCustomKwReset) } catch {}
                  }}>
                    <RotateCcw className="mr-1.5 h-3.5 w-3.5" /> {t.settings.resetCustom}
                  </Button>
                  <Button size="sm" variant="outline" onClick={handleResetSectors} disabled={resettingSectors}>
                    <RefreshCw className={cn("mr-1.5 h-3.5 w-3.5", resettingSectors && "animate-spin")} />
                    {resettingSectors ? t.settings.resetting : t.settings.resetSectorMapping}
                  </Button>
                </div>
              </CardContent>
            </Card>
          )}
          {/* ── 数据备份 ── */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <Archive className="h-5 w-5 text-primary" />
                {t.settings.dataBackup}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-sm text-muted-foreground">{t.settings.backupHint}</p>
              <Button
                variant="outline"
                size="sm"
                onClick={async () => {
                  try {
                    await api.exportZip()
                    toast.success(t.settings.backupExported)
                  } catch (e) {
                    toast.error(e instanceof Error ? e.message : t.settings.backupFailed)
                  }
                }}
              >
                <FileDown className="mr-1.5 h-4 w-4" />
                {t.settings.exportZip}
              </Button>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}
