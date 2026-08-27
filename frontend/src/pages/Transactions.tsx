import { useState, useEffect, useMemo, useRef } from "react"
import { useSearchParams, useLocation, useNavigate } from "react-router-dom"
import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { Transaction, CSVParseResult, FundMeta, Fund, Position, CalcFeeResponse, AutoInvestPlan } from "@/api/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import LogoSpinner from "@/components/LogoSpinner"
import ErrorState from "@/components/ErrorState"
import FeeBreakdownCard from "@/components/FeeBreakdownCard"
import { money, localDateStr } from "@/lib/format"
import PageHeader from "@/components/PageHeader"
import LoadingState from "@/components/LoadingState"
import EmptyState from "@/components/EmptyState"
import { cn } from "@/lib/utils"
import { toast } from "sonner"
import { Search, Plus, Pencil, Trash2, Download, Upload, FileDown, ChevronUp, ChevronDown, Loader2, Receipt, ArrowUpDown, Repeat, Gift, Camera } from "lucide-react"
import { getChannels, getChannelsAsync, saveChannels } from "@/lib/channels"
import { makeSortHeader } from "@/components/SortHeader"
import { useLang } from "@/i18n/LanguageContext"
import ConfirmDialog from "@/components/ConfirmDialog"
import TransactionDetailDialog from "@/components/TransactionDetailDialog"
import DividendCheckDialog from "@/components/DividendCheckDialog"
import ScreenshotImportDialog from "@/components/ScreenshotImportDialog"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog"

function actionBadgeClass(action: string): string {
  switch (action) {
    case "buy": return ""
    case "sell": return ""
    case "dividend": return "text-primary border-primary/30 bg-primary/10"
    case "reinvest": return "text-info border-info/30 bg-info/10"
    default: return ""
  }
}

export default function Transactions() {
  const { t } = useLang()
  const [searchParams, setSearchParams] = useSearchParams()
  const location = useLocation()
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState("form")
  const [editingTx, setEditingTx] = useState<Transaction | null>(null)
  const [listReloadKey, setListReloadKey] = useState(0)
  const [prefill, setPrefill] = useState<{ code: string; action: string; channel?: string; amount?: string; date?: string; note?: string; alert_id?: number; tp_sl_alert_id?: number } | null>(null)
  const [autoInvestPrefillCode, setAutoInvestPrefillCode] = useState<string | null>(null)
  const [autoInvestPrefillChannel, setAutoInvestPrefillChannel] = useState<string | undefined>(undefined)
  const [dividendDialogOpen, setDividendDialogOpen] = useState(false)
  const [screenshotOpen, setScreenshotOpen] = useState(false)
  const [dividendAlertCount, setDividendAlertCount] = useState(0)
  const consumedEditTx = useRef(false)

  // 从 URL 参数消费预填数据（从持仓页/分红检查跳转过来）
  useEffect(() => {
    const code = searchParams.get("code")
    const action = searchParams.get("action")
    const channel = searchParams.get("channel")
    const amount = searchParams.get("amount")
    const date = searchParams.get("date")
    const note = searchParams.get("note")
    const alertId = searchParams.get("alert_id")
    const tpSlAlertId = searchParams.get("tp_sl_alert_id")
    const tab = searchParams.get("tab")
    if (tab === "auto-invest" && code) {
      setAutoInvestPrefillCode(code)
      setAutoInvestPrefillChannel(channel || undefined)
      setActiveTab("auto-invest")
      setSearchParams({}, { replace: true })
    } else if (code) {
      setPrefill({ code, action: action || "buy", channel: channel || undefined, amount: amount || undefined, date: date || undefined, note: note ? decodeURIComponent(note) : undefined, alert_id: alertId ? Number(alertId) : undefined, tp_sl_alert_id: tpSlAlertId ? Number(tpSlAlertId) : undefined })
      setActiveTab("form")
      setSearchParams({}, { replace: true })
    }
  }, [searchParams, setSearchParams])

  // 从 navigator.state 消费编辑数据（从详情页跳转过来）
  useEffect(() => {
    if (consumedEditTx.current) return
    const state = location.state as { editTx?: Transaction } | null
    if (state?.editTx) {
      consumedEditTx.current = true
      setEditingTx(state.editTx)
      setPrefill(null)
      setActiveTab("form")
      window.history.replaceState({}, "")
    }
  }, [location.state])

  useEffect(() => {
    let active = true
    const fetchCount = () => {
      api.getPendingDividendAlertCount().then(r => { if (active) setDividendAlertCount(r.count) }).catch(() => {})
    }
    fetchCount()
    const timer = setInterval(fetchCount, 60000)
    return () => { active = false; clearInterval(timer) }
  }, [])

  const handleEdit = (tx: Transaction) => {
    consumedEditTx.current = false
    setEditingTx(tx)
    setPrefill(null)
    setActiveTab("form")
  }

  const handleFormDone = (fundCode?: string) => {
    setEditingTx(null)
    setPrefill(null)
    setListReloadKey((k) => k + 1)
    if (fundCode) navigate(`/fund/${fundCode}`)
  }

  const handleViewFund = (code: string) => navigate(`/fund/${code}`)

  return (
    <div className="space-y-6">
      <PageHeader title={t.transactions.title} />
      <div className="flex items-center justify-end">
        <Button variant="outline" size="sm" onClick={() => setScreenshotOpen(true)}>
          <Camera className="mr-1.5 h-4 w-4" />
          <span className="hidden sm:inline">{t.transactions.screenshotImport}</span>
          <span className="sm:hidden">截图</span>
        </Button>
      </div>
      <ScreenshotImportDialog open={screenshotOpen} onOpenChange={setScreenshotOpen} onImported={() => setListReloadKey((k) => k + 1)} />
      <DividendCheckDialog open={dividendDialogOpen} onOpenChange={setDividendDialogOpen} />
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="grid w-full grid-cols-4 sm:inline-flex sm:w-auto">
          <TabsTrigger value="form" className="gap-1.5">
            <span className="relative">
              <Plus className="h-4 w-4" />
              {dividendAlertCount > 0 && (
                <span className="absolute -top-1 -right-1.5 h-2 w-2 rounded-full bg-red-500 ring-1 ring-background" />
              )}
            </span>
            <span className="hidden sm:inline">{t.transactions.singleEntry}</span><span className="sm:hidden">{t.transactions.singleEntryShort}</span>
          </TabsTrigger>
          <TabsTrigger value="list" className="gap-1.5">
            <Receipt className="h-4 w-4" /> <span className="hidden sm:inline">{t.transactions.transactionFlow}</span><span className="sm:hidden">{t.transactions.flowShort}</span>
          </TabsTrigger>
          <TabsTrigger value="csv" className="gap-1.5">
            <ArrowUpDown className="h-4 w-4" /> <span className="hidden sm:inline">{t.transactions.csvImportExport}</span><span className="sm:hidden">CSV</span>
          </TabsTrigger>
          <TabsTrigger value="auto-invest" className="gap-1.5">
            <Repeat className="h-4 w-4" /> <span className="hidden sm:inline">{t.transactions.autoInvestPlans}</span><span className="sm:hidden">{t.transactions.autoInvestShort}</span>
          </TabsTrigger>
        </TabsList>
        <TabsContent value="form">
          <TransactionForm
            editingTx={editingTx}
            prefill={prefill}
            onPrefillConsumed={() => setPrefill(null)}
            onDone={handleFormDone}
            onCheckDividends={() => setDividendDialogOpen(true)}
            dividendAlertCount={dividendAlertCount}
          />
        </TabsContent>
        <TabsContent value="list">
          <TransactionList key={listReloadKey} onEdit={handleEdit} onViewFund={handleViewFund} />
        </TabsContent>
        <TabsContent value="csv"><CSVImportExport /></TabsContent>
        <TabsContent value="auto-invest"><AutoInvestPlansPanel prefillCode={autoInvestPrefillCode} prefillChannel={autoInvestPrefillChannel} onPrefillConsumed={() => { setAutoInvestPrefillCode(null); setAutoInvestPrefillChannel(undefined) }} /></TabsContent>
      </Tabs>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 单笔录入 / 编辑
// ---------------------------------------------------------------------------
function TransactionForm({ editingTx, prefill, onPrefillConsumed, onDone, onCheckDividends, dividendAlertCount }: {
  editingTx: Transaction | null
  prefill: { code: string; action: string; channel?: string; amount?: string; date?: string; note?: string; alert_id?: number; tp_sl_alert_id?: number } | null
  onPrefillConsumed: () => void
  onDone: (fundCode?: string) => void
  onCheckDividends?: () => void
  dividendAlertCount: number
}) {
  const { t } = useLang()
  const [code, setCode] = useState("")
  const [meta, setMeta] = useState<FundMeta | null>(null)
  const [fetching, setFetching] = useState(false)
  const [action, setAction] = useState("buy")
  const [date, setDate] = useState(() => localDateStr())
  const [channels, setChannels] = useState<string[]>(() => getChannels())
  const [channel, setChannel] = useState(channels[0])
  const [amount, setAmount] = useState("")
  const [shares, setShares] = useState("")
  const [nav, setNav] = useState("")
  const [fee, setFee] = useState("0")
  const [customChannel, setCustomChannel] = useState("")
  const [note, setNote] = useState("")
  const [saving, setSaving] = useState(false)
  const [afterThree, setAfterThree] = useState(false)
  const [navLoading, setNavLoading] = useState(false)
  const [navNotFound, setNavNotFound] = useState(false)
  const [feeCalcResult, setFeeCalcResult] = useState<CalcFeeResponse | null>(null)
  const [feeCalcLoading, setFeeCalcLoading] = useState(false)
  const feeManuallyEdited = useRef(false)
  const feeCalcTimer = useRef<ReturnType<typeof setTimeout>>()
  const [pendingAlertId, setPendingAlertId] = useState<number | null>(null)
  const [pendingTpSlAlertId, setPendingTpSlAlertId] = useState<number | null>(null)
  const isEditing = !!editingTx

  // 持仓数据（用于卖出时校验 + 快捷填入）
  const { data: positions } = useApi<Position[]>(() => api.getPositions(false), [])

  // 当前基金+渠道的持有份额（编辑卖出时加回原份额）
  const heldShares = useMemo(() => {
    if (!positions || !code.trim() || action !== "sell") return 0
    const effectiveChannel = customChannel.trim() || channel
    const matching = positions.filter(p =>
      p.fund_code === code.trim() &&
      p.channel === effectiveChannel &&
      p.is_open
    )
    let total = matching.reduce((s, p) => s + p.held_shares, 0)
    if (isEditing && editingTx?.action === "sell" && editingTx.shares) {
      total += editingTx.shares
    }
    return total
  }, [positions, code, action, channel, customChannel, isEditing, editingTx])

  // 编辑模式：回填表单
  useEffect(() => {
    if (!editingTx) return
    setCode(editingTx.fund_code)
    setAction(editingTx.action)
    setDate(editingTx.date)
    setAmount(editingTx.amount?.toString() ?? "")
    setShares(editingTx.shares?.toString() ?? "")
    setNav(editingTx.nav?.toString() ?? "")
    setFee(editingTx.fee?.toString() ?? "0")
    feeManuallyEdited.current = false
    setFeeCalcResult(null)

    // 渠道：预设值走 select，非预设值走 customChannel
    if (editingTx.channel && channels.includes(editingTx.channel)) {
      setChannel(editingTx.channel)
      setCustomChannel("")
    } else {
      setChannel("其它")
      setCustomChannel(editingTx.channel ?? "")
    }

    // 备注 + T+1 标记（is_t1 字段，不再在 note 里追加文本）
    setNote((editingTx.note ?? "").trim())
    setAfterThree(!!editingTx.is_t1)

    // 尝试回填基金信息
    if (editingTx.fund_code) {
      api.fetchFundMeta(editingTx.fund_code).then((m) => setMeta(m)).catch(() => {})
    }
  }, [editingTx])

  // 预填模式：从持仓页/分红检查跳转过来，回填代码 + 操作方向 + 渠道 + 金额/日期/备注
  useEffect(() => {
    if (!prefill) return
    setCode(prefill.code)
    setAction(prefill.action)
    setShares(""); setNav(""); setFee("0")
    setAmount(prefill.amount ?? "")
    setDate(prefill.date ?? localDateStr())
    setNote(prefill.note ?? "")
    setAfterThree(false); setCustomChannel("")
    setMeta(null)
    setFeeCalcResult(null); feeManuallyEdited.current = false
    setPendingAlertId(prefill.alert_id ?? null)
    setPendingTpSlAlertId(prefill.tp_sl_alert_id ?? null)
    // 渠道预填：预设渠道走 select，自定义渠道走 customChannel
    if (prefill.channel) {
      if (channels.includes(prefill.channel)) {
        setChannel(prefill.channel)
      } else {
        setChannel("其它")
        setCustomChannel(prefill.channel)
      }
    }
    if (prefill.code.trim()) {
      setFetching(true)
      api.fetchFundMeta(prefill.code.trim())
        .then((m) => { setMeta(m); setFetching(false) })
        .catch(() => setFetching(false))
    }
    onPrefillConsumed()
  }, [prefill, onPrefillConsumed])

  // 自动查询日期对应净值（T+1 则查次日）
  const effectiveNavDate = useMemo(() => {
    if (!date) return ""
    if (!afterThree) return date
    const d = new Date(date)
    d.setDate(d.getDate() + 1)
    return localDateStr(d)
  }, [date, afterThree])

  useEffect(() => {
    if (!code.trim() || !effectiveNavDate) return
    setNavLoading(true)
    setNavNotFound(false)
    api.getNavForDate(code.trim(), effectiveNavDate)
      .then((rows) => {
        if (rows.length > 0) {
          setNav(rows[0].nav.toFixed(4))
        } else {
          setNav("")
          setNavNotFound(true)
        }
      })
      .catch(() => { setNav(""); setNavNotFound(true) })
      .finally(() => setNavLoading(false))
  }, [code, effectiveNavDate])

  // 自动计算手续费（防抖 500ms）
  useEffect(() => {
    if (feeCalcTimer.current) clearTimeout(feeCalcTimer.current)
    if (!code.trim()) { setFeeCalcResult(null); return }

    const amt = parseFloat(amount) || 0
    const sh = parseFloat(shares) || 0

    if (action === "buy" && amt > 0) {
      setFeeCalcLoading(true)
      feeCalcTimer.current = setTimeout(async () => {
        try {
          const res = await api.calcFundFee(code.trim(), { action: "buy", amount: amt })
          setFeeCalcResult(res)
          if (!feeManuallyEdited.current) {
            setFee(res.fee.toFixed(2))
          }
        } catch { /* ignore */ }
        finally { setFeeCalcLoading(false) }
      }, 500)
    } else if (action === "sell" && sh > 0 && effectiveNavDate) {
      setFeeCalcLoading(true)
      feeCalcTimer.current = setTimeout(async () => {
        try {
          const res = await api.calcFundFee(code.trim(), { action: "sell", shares: sh, date: effectiveNavDate })
          setFeeCalcResult(res)
          if (!feeManuallyEdited.current) {
            setFee(res.fee.toFixed(2))
          }
        } catch { /* ignore */ }
        finally { setFeeCalcLoading(false) }
      }, 500)
    } else {
      setFeeCalcResult(null)
    }

    return () => { if (feeCalcTimer.current) clearTimeout(feeCalcTimer.current) }
  }, [code, action, amount, shares, effectiveNavDate])

  // 从服务端加载渠道列表（多设备同步）
  useEffect(() => {
    getChannelsAsync().then((server) => {
      setChannels(server)
      if (!channels.includes(channel)) setChannel(server[0])
    }).catch(() => {})
  }, [])

  const handleFeeChange = (v: string) => {
    feeManuallyEdited.current = true
    setFee(v)
  }

  // 买入：金额 - 手续费 → 份额；卖出：份额 × 净值 - 手续费 → 金额
  const a = parseFloat(amount) || 0
  const f = parseFloat(fee) || 0
  const n = parseFloat(nav) || 0
  const s = parseFloat(shares) || 0

  // 买入时自动算份额（自动计算值，用户可手动覆盖）
  const autoShares = action === "buy" && a > 0 && n > 0 && a - f > 0
    ? ((a - f) / n).toFixed(2)
    : ""
  // 卖出/再投资时自动算金额（卖出扣手续费，再投资无手续费）
  const autoAmount = ((action === "sell" && s > 0 && n > 0) || (action === "reinvest" && s > 0 && n > 0))
    ? (action === "sell" ? (s * n - f) : (s * n)).toFixed(2)
    : ""

  const handleFetchMeta = async (silent = false) => {
    if (!code.trim()) return
    setFetching(true)
    try {
      const m = await api.fetchFundMeta(code.trim())
      setMeta(m)
      if (m.ok && !silent) toast.success(t.transactions.fundRecognized.replace("{name}", m.fund_name))
    } catch (e) { if (!silent) toast.error(`${t.transactions.fetchFailed}: ${e}`) }
    finally { setFetching(false) }
  }

  const handleCodeBlur = () => {
    const c = code.trim()
    if (c.length === 6 && /^\d{6}$/.test(c) && !meta) {
      handleFetchMeta(true)
    }
  }

  const resetForm = () => {
    setCode(""); setMeta(null); setAction("buy"); setDate(localDateStr())
    setAmount(""); setShares(""); setNav(""); setFee("0")
    setCustomChannel(""); setNote(""); setAfterThree(false)
    setFeeCalcResult(null); feeManuallyEdited.current = false
    setPendingAlertId(null)
    setPendingTpSlAlertId(null)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!code.trim()) { toast.error(t.transactions.fundCodeRequired); return }
    if (!date) { toast.error(t.transactions.dateRequired); return }

    // 买入：优先手动输入的份额，无则用自动计算值
    const manualShares = parseFloat(shares) || null
    const finalShares = action === "buy" ? (manualShares || parseFloat(autoShares) || null) : (manualShares || null)
    const finalAmount = action === "sell" || action === "reinvest"
      ? (parseFloat(amount) || parseFloat(autoAmount) || null)
      : (parseFloat(amount) || null)
    const finalNav = action === "dividend" ? null : (parseFloat(nav) || null)

    // 买入至少有金额，卖出/再投资至少有份额，分红至少有金额（净值可能尚未公布，留空则待确认）
    if ((action === "buy" || action === "dividend") && !finalAmount) {
      toast.error(action === "buy" ? t.transactions.buyAmountRequired : t.transactions.dividendAmountRequired)
      return
    }
    if ((action === "sell" || action === "reinvest") && !finalShares) {
      toast.error(action === "sell" ? t.transactions.sellSharesRequired : t.transactions.reinvestSharesRequired)
      return
    }

    // 卖出不能超过持有份额
    if (action === "sell" && heldShares > 0 && finalShares && finalShares > heldShares) {
      toast.error(t.transactions.sellExceedsHolding.replace("{n}", heldShares.toFixed(2)))
      return
    }

    const payload = {
      fund_code: code.trim(), action, date,
      amount: finalAmount,
      shares: finalShares,
      nav: finalNav,
      fee: parseFloat(fee) || 0,
      channel: customChannel.trim() || channel,
      note: note.trim(),
      is_t1: afterThree,
    }

    setSaving(true)
    try {
      if (isEditing && editingTx?.id) {
        await api.updateTransaction(editingTx.id, payload)
        toast.success(t.transactions.txUpdatedToast.replace("{action}", t.actionLabels[action as keyof typeof t.actionLabels] ?? action).replace("{code}", code.trim()))
      } else {
        const result = await api.addTransaction(payload)
        toast.success(t.transactions.txSavedToast.replace("{action}", t.actionLabels[action as keyof typeof t.actionLabels] ?? action).replace("{code}", code.trim()))
        // 从分红提醒跳转来：保存成功后标记 alert 为 confirmed
        if (pendingAlertId) {
          api.updateDividendAlert(pendingAlertId, "confirmed", result.id).catch(() => {})
          setPendingAlertId(null)
        }
        // 从止盈止损提醒跳转来：保存成功后标记 alert 为 confirmed
        if (pendingTpSlAlertId) {
          api.updateAlert(pendingTpSlAlertId, "confirmed").catch(() => {})
          setPendingTpSlAlertId(null)
        }
      }
      // 自动添加自定义渠道到系统列表
      const finalChannel = customChannel.trim() || channel
      if (finalChannel && !channels.includes(finalChannel)) {
        const next = [...channels, finalChannel]
        setChannels(next)
        saveChannels(next).catch(() => {})
      }
      resetForm()
      onDone(code.trim())
    } catch (e) { toast.error(`${t.common.saveFailed}: ${e}`) }
    finally { setSaving(false) }
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">
            {isEditing ? `${t.transactions.editTransaction} #${editingTx?.id}` : t.transactions.singleEntry}
          </CardTitle>
          {onCheckDividends && !isEditing && (
            <Button variant="outline" size="sm" onClick={onCheckDividends} className="relative">
              <Gift className="h-4 w-4 mr-1.5" />
              {t.transactions.dividendCheck}
              {dividendAlertCount > 0 && (
                <span className="absolute -top-1.5 -right-1.5 inline-flex items-center justify-center min-w-[16px] h-[16px] px-1 rounded-full bg-red-500 text-white text-[10px] font-semibold ring-1 ring-background">
                  {dividendAlertCount > 99 ? "99+" : dividendAlertCount}
                </span>
              )}
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-5">
          {/* ── 基金代码 ── */}
          <div>
            <div className="flex gap-2">
              <div className="flex-1 max-w-[200px]">
                <Label className="mb-1.5 block text-xs text-muted-foreground">{t.transactions.fundCode}</Label>
                <Input
                  value={code} onChange={(e) => setCode(e.target.value)} onBlur={handleCodeBlur}
                  placeholder={t.transactions.fundCodePlaceholder} className="h-9"
                />
              </div>
              <div className="pt-5">
                <Button type="button" variant="outline" size="sm" onClick={() => handleFetchMeta(false)} disabled={fetching} className="h-9">
                  {fetching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Search className="h-3.5 w-3.5" />}
                </Button>
              </div>
              {meta?.ok && (
                <div className="pt-5 flex-1 min-w-0">
                  <p className="text-sm truncate">
                    <span className="font-medium">{meta.fund_name}</span>
                    <span className="text-muted-foreground mx-1.5">·</span>
                    <span className="text-xs text-muted-foreground">{meta.fund_type}{meta.sector ? ` · ${meta.sector}` : ""}</span>
                  </p>
                </div>
              )}
            </div>
          </div>

          <div className="border-t border-border/60" />

          {/* ── 操作 / 日期 / 渠道 ── */}
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
            <div>
              <Label className="mb-1.5 block text-xs text-muted-foreground">{t.common.actions}</Label>
              <Select value={action} onChange={(e) => setAction(e.target.value)} className="h-9">
                <option value="buy">{t.transactions.buy}</option>
                <option value="sell">{t.transactions.sell}</option>
                <option value="dividend">{t.transactions.dividend}</option>
                <option value="reinvest">{t.transactions.reinvest}</option>
              </Select>
            </div>
            <div className="sm:col-span-2">
              <Label className="mb-1.5 block text-xs text-muted-foreground">{t.transactions.tradeDate}</Label>
              <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="h-9" />
              <div className="mt-1 flex items-center gap-3">
                <p className="text-[11px] text-muted-foreground leading-relaxed">
                  {t.transactions.tradeDateHint}
                </p>
                <label className="shrink-0 flex items-center gap-1 text-[11px] cursor-pointer select-none">
                  <input type="checkbox" checked={afterThree} onChange={(e) => setAfterThree(e.target.checked)} className="rounded" />
                  {t.transactions.afterThreeOClock}
                </label>
              </div>
            </div>
            <div>
              <Label className="mb-1.5 block text-xs text-muted-foreground">{t.common.channel}</Label>
              <Select value={channel} onChange={(e) => setChannel(e.target.value)} className="h-9">
                {channels.map((c) => <option key={c} value={c}>{c}</option>)}
              </Select>
            </div>
          </div>

          <div className="border-t border-border/60" />

          {/* ── 金额 / 份额 / 净值 / 手续费 ── */}
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
            {action === "buy" && (
              <>
                <div>
                  <Label className="mb-1.5 block text-xs text-muted-foreground">{t.transactions.amountYuan}</Label>
                  <Input type="number" step="0.01" min="0" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00" className="h-9" autoFocus={!isEditing} />
                </div>
                <div>
                  <Label className="mb-1.5 block text-xs text-muted-foreground">
                    {t.common.shares} <span className="text-primary">{t.transactions.editable}</span>
                  </Label>
                  <Input type="number" step="0.01" value={shares || autoShares} onChange={(e) => setShares(e.target.value)} className="h-9" placeholder={autoShares || "—"} />
                </div>
              </>
            )}
            {action === "sell" && (
              <>
                <div>
                  <Label className="mb-1.5 block text-xs text-muted-foreground">
                    {t.common.shares}{heldShares > 0 && <span className="text-muted-foreground/70 ml-1">{t.transactions.holding.replace("{n}", heldShares.toFixed(2))}</span>}
                  </Label>
                  <Input type="number" step="0.01" min="0" value={shares} onChange={(e) => setShares(e.target.value)} placeholder="0.00" className="h-9" autoFocus={!isEditing} />
                  {heldShares > 0 && (
                    <div className="mt-1.5 flex gap-1.5">
                      <Button type="button" variant="outline" size="sm" className="h-6 px-2 text-[11px]" onClick={() => setShares((heldShares * 0.25).toFixed(2))}>1/4</Button>
                      <Button type="button" variant="outline" size="sm" className="h-6 px-2 text-[11px]" onClick={() => setShares((heldShares * 1 / 3).toFixed(2))}>1/3</Button>
                      <Button type="button" variant="outline" size="sm" className="h-6 px-2 text-[11px]" onClick={() => setShares((heldShares * 0.5).toFixed(2))}>1/2</Button>
                      <Button type="button" variant="outline" size="sm" className="h-6 px-2 text-[11px]" onClick={() => setShares((heldShares * 0.75).toFixed(2))}>3/4</Button>
                      <Button type="button" variant="outline" size="sm" className="h-6 px-2 text-[11px]" onClick={() => setShares(heldShares.toFixed(2))}>{t.common.all}</Button>
                    </div>
                  )}
                </div>
                <div>
                  <Label className="mb-1.5 block text-xs text-muted-foreground">
                    {t.common.amount} <span className="text-primary">{t.transactions.editable}</span>
                  </Label>
                  <Input type="number" step="0.01" value={amount || autoAmount} onChange={(e) => setAmount(e.target.value)} className="h-9" placeholder={autoAmount || "—"} />
                </div>
              </>
            )}
            {action === "dividend" && (
              <div className="sm:col-span-2">
                <Label className="mb-1.5 block text-xs text-muted-foreground">{t.transactions.dividendAmountYuan}</Label>
                <Input type="number" step="0.01" min="0" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder={t.transactions.cashReceived} className="h-9" autoFocus={!isEditing} />
                <p className="mt-1 text-[11px] text-muted-foreground">{t.transactions.dividendHint}</p>
              </div>
            )}
            {action === "reinvest" && (
              <>
                <div>
                  <Label className="mb-1.5 block text-xs text-muted-foreground">{t.transactions.dividendShares}</Label>
                  <Input type="number" step="0.01" min="0" value={shares} onChange={(e) => setShares(e.target.value)} placeholder={t.transactions.newSharesPlaceholder} className="h-9" autoFocus={!isEditing} />
                </div>
                <div>
                  <Label className="mb-1.5 block text-xs text-muted-foreground">
                    {t.common.amount} <span className="text-primary">{t.transactions.automatic}</span>
                  </Label>
                  <Input type="number" step="0.01" value={autoAmount} readOnly className="h-9 bg-muted/50" placeholder="—" />
                </div>
              </>
            )}
            {/* 净值：买入/卖出/再投资需要，分红不需要 */}
            {action !== "dividend" && (
              <div>
                <Label className="mb-1.5 block text-xs text-muted-foreground">{t.transactions.tradeNav}</Label>
                <div className="relative">
                  <Input
                    type="number" step="0.0001" min="0" value={nav}
                    onChange={(e) => { setNav(e.target.value); setNavNotFound(false) }}
                    placeholder={navLoading ? t.transactions.querying : "0.0000"}
                    className={cn("h-9", navLoading && "pr-8", navNotFound && "border-warning/50")}
                  />
                  {navLoading && (
                    <Loader2 className="absolute right-2.5 top-1/2 -translate-y-1/2 h-4 w-4 animate-spin text-muted-foreground" />
                  )}
                </div>
                <p className={cn("mt-1 text-[11px]", navNotFound ? "text-warning" : "text-muted-foreground")}>
                  {navLoading ? t.transactions.queryingNav : navNotFound ? t.transactions.navNotFoundHint : t.transactions.navAutoHint}
                </p>
              </div>
            )}
            {/* 手续费：买入/卖出需要，分红/再投资不需要 */}
            {action !== "dividend" && action !== "reinvest" && (
              <div>
                <Label className="mb-1.5 block text-xs text-muted-foreground">
                  {t.transactions.feeYuan}
                  {feeCalcLoading && <Loader2 className="inline ml-1 h-3 w-3 animate-spin" />}
                </Label>
                <Input type="number" step="0.01" min="0" value={fee} onChange={(e) => handleFeeChange(e.target.value)} className="h-9" />
                {feeCalcResult && (
                  <FeeBreakdownCard result={feeCalcResult} action={action === "sell" ? "sell" : "buy"} />
                )}
              </div>
            )}
          </div>

          <div className="border-t border-border/60" />

          {/* ── 自定义渠道 / 备注 ── */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <Label className="mb-1.5 block text-xs text-muted-foreground">{t.transactions.customChannel}</Label>
              <Input value={customChannel} onChange={(e) => setCustomChannel(e.target.value)} placeholder={t.transactions.customChannelPlaceholder} className="h-9" />
            </div>
            <div>
              <Label className="mb-1.5 block text-xs text-muted-foreground">{t.transactions.remarkOptional}</Label>
              <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder={t.transactions.remarkPlaceholder} className="h-9" />
            </div>
          </div>

          <div className="flex gap-2 pt-1">
            <Button type="submit" disabled={saving} className="flex-1 h-9">
              {saving ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : (isEditing ? <Pencil className="mr-1.5 h-4 w-4" /> : <Plus className="mr-1.5 h-4 w-4" />)}
              {saving ? t.transactions.saving : isEditing ? t.transactions.updateTransaction : t.transactions.saveTransaction}
            </Button>
            {isEditing && (
              <Button type="button" variant="outline" onClick={() => { resetForm(); onDone() }} className="h-9">
                {t.common.cancel}
              </Button>
            )}
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// 交易流水
// ---------------------------------------------------------------------------
function TransactionList({ onEdit, onViewFund }: { onEdit: (tx: Transaction) => void; onViewFund: (fundCode: string) => void }) {
  const { t } = useLang()
  const { data: txs, loading, error, reload } = useApi<Transaction[]>(() => api.getTransactions())
  const [funds, setFunds] = useState<Record<string, Fund>>({})
  const [showClearConfirm, setShowClearConfirm] = useState(false)
  const [clearConfirmText, setClearConfirmText] = useState("")
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null)
  const [sortField, setSortField] = useState("date")
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc")
  const [searchQuery, setSearchQuery] = useState("")
  const [actionFilter, setActionFilter] = useState("")
  const [dateRange, setDateRange] = useState(() => localStorage.getItem("zfundpilot_tx_dateRange") || "30d")
  const [customStart, setCustomStart] = useState(() => localStorage.getItem("zfundpilot_tx_customStart") || "")
  const [customEnd, setCustomEnd] = useState(() => localStorage.getItem("zfundpilot_tx_customEnd") || "")
  const [visibleCount, setVisibleCount] = useState(50)
  const [viewingTx, setViewingTx] = useState<Transaction | null>(null)

  // 持久化筛选范围
  useEffect(() => { localStorage.setItem("zfundpilot_tx_dateRange", dateRange) }, [dateRange])
  useEffect(() => { localStorage.setItem("zfundpilot_tx_customStart", customStart) }, [customStart])
  useEffect(() => { localStorage.setItem("zfundpilot_tx_customEnd", customEnd) }, [customEnd])
  // 切换筛选条件时重置分页
  useEffect(() => { setVisibleCount(50) }, [searchQuery, actionFilter, dateRange, customStart, customEnd])

  // Load fund names
  useApi(() => api.getFunds(), []).data?.forEach((f: Fund) => {
    if (!funds[f.fund_code]) setFunds((prev) => ({ ...prev, [f.fund_code]: f }))
  })

  const toggleSort = (field: string) => {
    if (sortField === field) {
      setSortDir(sortDir === "asc" ? "desc" : "asc")
    } else {
      setSortField(field)
      setSortDir("desc")
    }
  }

  const filteredTxs = useMemo(() => {
    if (!txs) return txs
    const q = searchQuery.trim().toLowerCase()
    let startDate = ""
    let endDate = ""
    if (dateRange !== "all") {
      const today = new Date()
      const todayStr = localDateStr(today)
      if (dateRange === "30d") {
        const d = new Date(today)
        d.setDate(d.getDate() - 30)
        startDate = localDateStr(d)
        endDate = todayStr
      } else if (dateRange === "month") {
        startDate = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-01`
        endDate = todayStr
      } else if (dateRange === "year") {
        startDate = `${today.getFullYear()}-01-01`
        endDate = todayStr
      } else if (dateRange === "custom") {
        startDate = customStart
        endDate = customEnd
      }
    }
    return txs.filter((t) => {
      if (q) {
        const name = funds[t.fund_code]?.fund_name?.toLowerCase() ?? ""
        if (!t.fund_code.toLowerCase().includes(q) && !name.includes(q)) return false
      }
      if (actionFilter && t.action !== actionFilter) return false
      if (startDate && t.date < startDate) return false
      if (endDate && t.date > endDate) return false
      return true
    })
  }, [txs, searchQuery, actionFilter, dateRange, customStart, customEnd, funds])

  const sortedTxs = useMemo(() => {
    if (!filteredTxs) return filteredTxs
    return [...filteredTxs].sort((a, b) => {
      const getVal = (t: Transaction): string | number => {
        if (sortField === "date") return t.date
        if (sortField === "fund_code") return t.fund_code
        if (sortField === "amount") return t.amount ?? 0
        if (sortField === "shares") return t.shares ?? 0
        if (sortField === "nav") return t.nav ?? 0
        if (sortField === "fee") return t.fee ?? 0
        return t.id ?? 0
      }
      const va = getVal(a)
      const vb = getVal(b)
      const cmp = typeof va === "string" && typeof vb === "string"
        ? va.localeCompare(vb)
        : (va as number) - (vb as number)
      return sortDir === "asc" ? cmp : -cmp
    })
  }, [filteredTxs, sortField, sortDir])

  const visibleTxs = useMemo(() => {
    if (!sortedTxs) return sortedTxs
    return sortedTxs.slice(0, visibleCount)
  }, [sortedTxs, visibleCount])

  const SortHeader = makeSortHeader({ sortField, sortDir, toggleSort })

  if (error) return <ErrorState message={error} onRetry={reload} />
  if (loading) return <LoadingState size="md" />

  const handleDelete = async (id: number) => {
    try {
      await api.deleteTransaction(id)
      toast.success(t.common.deleted)
      reload()
    } catch (e) { toast.error(`${t.common.deleteFailed}: ${e}`) }
  }

  const handleClearAll = async () => {
    try {
      await api.deleteAllTransactions()
      toast.success(t.transactions.allTransactionsCleared)
      setShowClearConfirm(false)
      setClearConfirmText("")
      reload()
    } catch (e) { toast.error(`${t.transactions.clearFailed}: ${e}`) }
  }

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle className="text-base">{t.transactions.transactionFlow}</CardTitle>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={async () => { try { await api.exportCsv(); toast.success(t.transactions.csvExported) } catch (e) { toast.error(String(e)) } }}>
            <FileDown className="mr-1 h-4 w-4" /> {t.transactions.exportCsv}
          </Button>
          <Button variant="destructive" size="sm" onClick={() => { setShowClearConfirm(true); setClearConfirmText("") }}>
            <Trash2 className="mr-1 h-4 w-4" /> {t.transactions.clearAll}
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {/* 筛选工具栏 */}
        {txs && txs.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 mb-4">
            <div className="relative">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
              <Input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={t.transactions.searchCodeName}
                className="h-8 w-40 pl-7 text-xs"
              />
            </div>
            <Select value={actionFilter} onChange={(e) => setActionFilter(e.target.value)} className="h-8 text-xs w-28">
              <option value="">{t.transactions.allActions}</option>
              <option value="buy">{t.transactions.buy}</option>
              <option value="sell">{t.transactions.sell}</option>
              <option value="dividend">{t.transactions.dividend}</option>
              <option value="reinvest">{t.transactions.reinvest}</option>
            </Select>
            <div className="flex items-center gap-1 ml-auto">
              {([["month", t.transactions.thisMonth], ["30d", t.transactions.last30Days], ["year", t.transactions.thisYear], ["all", t.common.all], ["custom", t.transactions.custom]] as const).map(([key, label]) => (
                <Button key={key} size="sm" variant={dateRange === key ? "default" : "outline"} className="h-8 text-xs px-2.5" onClick={() => setDateRange(key)}>
                  {label}
                </Button>
              ))}
            </div>
            {dateRange === "custom" && (
              <div className="flex items-center gap-1.5 w-full sm:w-auto">
                <Input type="date" value={customStart} onChange={(e) => setCustomStart(e.target.value)} className="h-8 text-xs w-40" />
                <span className="text-muted-foreground text-xs">{t.fundDetail.to}</span>
                <Input type="date" value={customEnd} onChange={(e) => setCustomEnd(e.target.value)} className="h-8 text-xs w-40" />
              </div>
            )}
          </div>
        )}

        {!txs || txs.length === 0 ? (
          <EmptyState title={t.transactions.noTransactionsFlow} />
        ) : filteredTxs && filteredTxs.length === 0 ? (
          <EmptyState title={t.transactions.noFilteredTransactions} />
        ) : (
<Table>
              <TableHeader>
                <TableRow>
                  <SortHeader field="id" className="w-16">ID</SortHeader>
                  <SortHeader field="date">{t.common.date}</SortHeader>
                  <TableHead>{t.common.actions}</TableHead>
                  <SortHeader field="fund_code">{t.common.code}</SortHeader>
                  <TableHead>{t.common.name}</TableHead>
                  <TableHead>{t.common.channel}</TableHead>
                  <SortHeader field="amount" className="text-right">{t.common.amount}</SortHeader>
                  <SortHeader field="shares" className="text-right">{t.common.shares}</SortHeader>
                  <SortHeader field="nav" className="text-right">{t.common.nav}</SortHeader>
                  <SortHeader field="fee" className="text-right">{t.common.fee}</SortHeader>
                  <TableHead>{t.common.note}</TableHead>
                  <TableHead className="w-20">{t.common.actions}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {visibleTxs?.map((tx) => {
                const fund = funds[tx.fund_code]
                return (
                  <TableRow key={tx.id} onClick={() => setViewingTx(tx)} className="cursor-pointer">
                    <TableCell className="text-xs text-muted-foreground">{tx.id}</TableCell>
                    <TableCell>{tx.date}</TableCell>
                    <TableCell>
                      <Badge
                        variant={tx.action === "buy" ? "success" : tx.action === "sell" ? "destructive" : "outline"}
                        className={actionBadgeClass(tx.action)}
                      >
                        {t.actionLabels[tx.action as keyof typeof t.actionLabels] ?? tx.action}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-mono text-xs">{tx.fund_code}</TableCell>
                    <TableCell>{fund?.fund_name ?? tx.fund_code}</TableCell>
                    <TableCell>{tx.channel || t.common.unlabeled}</TableCell>
                    <TableCell className="text-right tabular-nums">{tx.amount ? money(tx.amount) : "—"}</TableCell>
                    <TableCell className="text-right tabular-nums">{tx.shares?.toFixed(2) ?? "—"}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {tx.nav != null ? tx.nav.toFixed(4) : tx.action === "dividend" ? "—" : <Badge variant="outline" className="text-warning border-warning/40 bg-warning/10">{t.transactions.pendingConfirm}</Badge>}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{tx.fee || "—"}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{tx.note}</TableCell>
                    <TableCell>
                      <div className="flex gap-1">
                        <Button variant="ghost" size="icon" onClick={(e) => { e.stopPropagation(); onEdit(tx) }}>
                          <Pencil className="h-4 w-4 text-primary" />
                        </Button>
                        <Button variant="ghost" size="icon" onClick={(e) => { e.stopPropagation(); setConfirmDeleteId(tx.id!) }}>
                          <Trash2 className="h-4 w-4 text-destructive" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        )}
        {txs && txs.length > 0 && (
          <div className="mt-3 flex items-center justify-between">
            <p className="text-sm text-muted-foreground">
              {t.transactions.txCountSummary.replace("{filtered}", String(filteredTxs?.length ?? 0)).replace("{total}", String(txs.length))}
            </p>
            {filteredTxs && filteredTxs.length > visibleCount && (
              <Button variant="outline" size="sm" className="h-8" onClick={() => setVisibleCount((c) => c + 50)}>
                {t.transactions.loadMore}
              </Button>
            )}
          </div>
        )}
      </CardContent>

      {/* 删除单条确认弹窗 */}
      <TransactionDetailDialog
        tx={viewingTx}
        fundName={viewingTx ? funds[viewingTx.fund_code]?.fund_name : undefined}
        open={viewingTx != null}
        onOpenChange={(open) => { if (!open) setViewingTx(null) }}
        onEdit={(tx) => { setViewingTx(null); onEdit(tx) }}
        onViewFund={onViewFund}
      />
      <ConfirmDialog
        open={confirmDeleteId != null}
        onOpenChange={(open) => { if (!open) setConfirmDeleteId(null) }}
        title={t.common.confirmDelete}
        description={<>{t.fundDetail.confirmDeleteTxDesc}<strong>{t.fundDetail.irreversible}</strong></>}
        confirmText={t.common.delete}
        tone="destructive"
        onConfirm={async () => {
          if (confirmDeleteId != null) await handleDelete(confirmDeleteId)
        }}
      />

      {/* 清空确认弹窗 */}
      <Dialog open={showClearConfirm} onOpenChange={(open) => { if (!open) { setShowClearConfirm(false); setClearConfirmText("") } }}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle className="text-destructive">{t.transactions.clearAllTitle}</DialogTitle>
            <DialogDescription asChild>
              <div>
                {t.transactions.clearAllDesc}
                <p className="mt-3">
                  {t.transactions.typeToConfirm.replace("{phrase}", t.transactions.confirmClearPhrase)}
                </p>
              </div>
            </DialogDescription>
          </DialogHeader>
          <Input
            value={clearConfirmText}
            onChange={(e) => setClearConfirmText(e.target.value)}
            placeholder={t.transactions.confirmClearPhrase}
            onKeyDown={(e) => { if (e.key === "Enter" && clearConfirmText === t.transactions.confirmClearPhrase) { e.preventDefault(); handleClearAll() } }}
            autoFocus
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => { setShowClearConfirm(false); setClearConfirmText("") }}>
              {t.common.cancel}
            </Button>
            <Button variant="destructive" disabled={clearConfirmText !== t.transactions.confirmClearPhrase} onClick={handleClearAll}>
              {t.transactions.confirmClear}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// CSV 导入/导出
// ---------------------------------------------------------------------------
function CSVImportExport() {
  const { t } = useLang()
  const [parseResult, setParseResult] = useState<CSVParseResult | null>(null)
  const [parsing, setParsing] = useState(false)
  const [importing, setImporting] = useState(false)
  const [clearExisting, setClearExisting] = useState(false)
  const [fetchMeta, setFetchMeta] = useState(true)

  const handleFile = async (file: File | undefined) => {
    if (!file) return
    setParsing(true)
    try {
      const result = await api.parseCsv(file)
      setParseResult(result)
      if (result.transactions.length > 0) toast.success(t.transactions.parseSuccess.replace("{n}", String(result.transactions.length)))
      if (result.errors.length > 0) toast.warning(t.transactions.parseWarnings.replace("{n}", String(result.errors.length)))
    } catch (e) { toast.error(`${t.transactions.parseFailed}: ${e}`) }
    finally { setParsing(false) }
  }

  const handleImport = async () => {
    if (!parseResult?.transactions.length) return
    setImporting(true)
    try {
      const res = await api.confirmImport(parseResult.transactions, clearExisting, fetchMeta)
      toast.success(t.transactions.importSuccess.replace("{n}", String(res.imported)))
      setParseResult(null)
    } catch (e) { toast.error(`${t.transactions.importFailed}: ${e}`) }
    finally { setImporting(false) }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader><CardTitle className="text-base">{t.transactions.batchImportTitle}</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            {t.transactions.csvRequiredColumns}<code className="rounded bg-muted px-1">fund_code</code>、
            <code className="rounded bg-muted px-1">action</code>{t.transactions.csvActionHint}、
            <code className="rounded bg-muted px-1">date</code>；
            <code className="rounded bg-muted px-1">amount</code>/<code className="rounded bg-muted px-1">shares</code>/<code className="rounded bg-muted px-1">nav</code> {t.transactions.csvAtLeastTwo}
          </p>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => api.downloadTemplate()}>
              <Download className="mr-1 h-4 w-4" /> {t.transactions.downloadTemplate}
            </Button>
            <label className="inline-flex cursor-pointer items-center justify-center gap-2 rounded-md border border-input bg-background px-4 py-2 text-sm font-medium hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 active:scale-[0.98]">
              <Upload className="h-4 w-4" /> {parsing ? t.transactions.parsing : t.transactions.uploadCsv}
              <input type="file" accept=".csv" className="hidden" onChange={(e) => handleFile(e.target.files?.[0])} />
            </label>
          </div>

          {/* Parse errors */}
          {parseResult?.errors && parseResult.errors.length > 0 && (
            <div className="rounded-md border border-warning/30 bg-warning/10 p-3">
              <p className="mb-1 text-sm font-medium text-warning">⚠️ {t.transactions.parseWarnings.replace("{n}", String(parseResult.errors.length))}</p>
              <ul className="space-y-0.5 text-xs text-warning">
                {parseResult.errors.map((e, i) => <li key={i}>{e}</li>)}
              </ul>
            </div>
          )}

          {/* Preview table */}
          {parseResult?.transactions && parseResult.transactions.length > 0 && (
            <div className="space-y-3">
              <p className="text-sm font-medium">{t.transactions.parseSuccessPreview.replace("{n}", String(parseResult.transactions.length))}</p>
              <div className="max-h-64 overflow-auto rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t.common.code}</TableHead><TableHead>{t.common.actions}</TableHead><TableHead>{t.common.date}</TableHead>
                      <TableHead className="text-right">{t.common.amount}</TableHead><TableHead className="text-right">{t.common.shares}</TableHead>
                      <TableHead className="text-right">{t.common.nav}</TableHead><TableHead>{t.common.channel}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {parseResult.transactions.map((tx, i) => (
                      <TableRow key={i}>
                        <TableCell className="font-mono text-xs">{tx.fund_code}</TableCell>
                        <TableCell><Badge variant={tx.action === "buy" ? "success" : tx.action === "sell" ? "destructive" : "outline"} className={actionBadgeClass(tx.action)}>{t.actionLabels[tx.action as keyof typeof t.actionLabels] ?? tx.action}</Badge></TableCell>
                        <TableCell>{tx.date}</TableCell>
                        <TableCell className="text-right tabular-nums">{tx.amount ? money(tx.amount) : "—"}</TableCell>
                        <TableCell className="text-right tabular-nums">{tx.shares?.toFixed(2) ?? "—"}</TableCell>
                        <TableCell className="text-right tabular-nums">{tx.nav?.toFixed(4) ?? "—"}</TableCell>
                        <TableCell>{tx.channel || "—"}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-4">
                <label className="flex items-center gap-2 text-sm">
                  <input type="radio" checked={!clearExisting} onChange={() => setClearExisting(false)} /> {t.transactions.appendToExisting}
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input type="radio" checked={clearExisting} onChange={() => setClearExisting(true)} /> {t.transactions.clearAndReimport}
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={fetchMeta} onChange={(e) => setFetchMeta(e.target.checked)} /> {t.transactions.autoFetchMeta}
                </label>
              </div>

              <Button onClick={handleImport} disabled={importing}>
                <Upload className="mr-1 h-4 w-4" /> {importing ? t.transactions.importing : t.transactions.confirmImport}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">{t.transactions.exportTitle}</CardTitle></CardHeader>
        <CardContent>
          <Button variant="outline" onClick={() => api.exportCsv()}>
            <FileDown className="mr-1 h-4 w-4" /> {t.transactions.exportAsCsv}
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 定投计划
// ---------------------------------------------------------------------------

function AutoInvestPlansPanel({ prefillCode, prefillChannel, onPrefillConsumed }: { prefillCode?: string | null; prefillChannel?: string | undefined; onPrefillConsumed?: () => void }) {
  const { t } = useLang()
  const { data: plans, loading, error, reload } = useApi<AutoInvestPlan[]>(() => api.getAutoInvestPlans(), [])
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingPlan, setEditingPlan] = useState<AutoInvestPlan | null>(null)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState<number | null>(null)
  const [executing, setExecuting] = useState<number | null>(null)

  const [code, setCode] = useState("")
  const [amount, setAmount] = useState("")
  const [cadence, setCadence] = useState("week")
  const [dayOfWeek, setDayOfWeek] = useState("0")
  const [dayOfMonth, setDayOfMonth] = useState("15")
  const [channel, setChannel] = useState("")
  const [note, setNote] = useState(t.transactions.autoInvest)
  const [channels] = useState<string[]>(() => getChannels())

  useEffect(() => {
    if (prefillCode) {
      setCode(prefillCode)
      setChannel(prefillChannel || "")
      setEditingPlan(null)
      setAmount(""); setCadence("week"); setDayOfWeek("0")
      setDayOfMonth("15"); setNote(t.transactions.autoInvest)
      setDialogOpen(true)
      onPrefillConsumed?.()
    }
  }, [prefillCode]) // eslint-disable-line react-hooks/exhaustive-deps

  const cadenceDesc = (plan: AutoInvestPlan): string => {
    const base = plan.cadence === "daily" ? t.transactions.everyTradingDay
      : plan.cadence === "week" ? t.transactions.weekly
      : plan.cadence === "biweek" ? t.transactions.biweekly
      : plan.cadence === "month" ? t.transactions.monthly
      : plan.cadence
    if (plan.cadence === "daily") return base
    if (plan.cadence === "month" && plan.day_of_month != null) return `${base} ${plan.day_of_month}${t.transactions.dayOfMonthSuffix}`
    if (plan.day_of_week != null) {
      return `${base}${t.transactions.weekdays[plan.day_of_week] ?? ""}`
    }
    return base
  }

  const openCreate = () => {
    setEditingPlan(null)
    setCode(""); setAmount(""); setCadence("week"); setDayOfWeek("0")
    setDayOfMonth("15"); setChannel(""); setNote(t.transactions.autoInvest)
    setDialogOpen(true)
  }

  const openEdit = (plan: AutoInvestPlan) => {
    setEditingPlan(plan)
    setCode(plan.fund_code)
    setAmount(String(plan.amount))
    setCadence(plan.cadence)
    setDayOfWeek(String(plan.day_of_week ?? 0))
    setDayOfMonth(String(plan.day_of_month ?? 15))
    setChannel(plan.channel)
    setNote(plan.note)
    setDialogOpen(true)
  }

  const handleSave = async () => {
    if (!code.trim() || !amount || parseFloat(amount) <= 0) {
      toast.warning(t.transactions.codeAndAmountRequired); return
    }
    setSaving(true)
    try {
      const body = {
        fund_code: code.trim(),
        amount: parseFloat(amount),
        cadence,
        day_of_week: cadence === "daily" ? null : (cadence === "month" ? null : parseInt(dayOfWeek)),
        day_of_month: cadence === "month" ? parseInt(dayOfMonth) : null,
        channel,
        note,
      }
      if (editingPlan) {
        await api.updateAutoInvestPlan(editingPlan.id, body)
        toast.success(t.transactions.planUpdated)
      } else {
        await api.createAutoInvestPlan(body)
        toast.success(t.transactions.planCreated)
      }
      setDialogOpen(false)
      reload()
    } catch (e: any) {
      toast.error(e.message || t.common.saveFailed)
    } finally {
      setSaving(false)
    }
  }

  const handleToggle = async (plan: AutoInvestPlan) => {
    try {
      await api.toggleAutoInvestPlan(plan.id, !plan.enabled)
      toast.success(plan.enabled ? t.transactions.paused : t.transactions.enabled)
      reload()
    } catch (e: any) {
      toast.error(e.message || t.common.operationFailed)
    }
  }

  const handleDelete = async (id: number) => {
    try {
      await api.deleteAutoInvestPlan(id)
      toast.success(t.transactions.planDeleted)
      setDeleting(null)
      reload()
    } catch (e: any) {
      toast.error(e.message || t.common.deleteFailed)
    }
  }

  const handleExecute = async (plan: AutoInvestPlan) => {
    setExecuting(plan.id)
    try {
      const res = await api.executeAutoInvestPlan(plan.id)
      toast.success(t.transactions.planExecuteSuccess.replace("{id}", String(res.tx_id)))
      reload()
    } catch (e: any) {
      toast.error(e.message || t.transactions.executeFailed)
    } finally {
      setExecuting(null)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">{t.transactions.autoInvestDesc}</p>
        <Button size="sm" onClick={openCreate}>
          <Plus className="mr-1 h-4 w-4" /> {t.transactions.newPlan}
        </Button>
      </div>

      {loading ? (
        <LoadingState size="sm" />
      ) : error ? (
        <ErrorState message={t.common.loadFailed} onRetry={reload} />
      ) : !plans || plans.length === 0 ? (
        <EmptyState title={t.transactions.noPlans} description={t.transactions.noPlansHintClick} />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {plans.map((plan) => (
            <Card key={plan.id} className={cn(plan.enabled ? "" : "opacity-60")}>
              <CardHeader className="pb-2">
                <div className="flex items-start justify-between">
                  <div>
                    <CardTitle className="text-sm font-semibold">
                      {plan.fund_name || plan.fund_code}
                    </CardTitle>
                    <p className="text-xs text-muted-foreground mt-0.5">{plan.fund_code}</p>
                  </div>
                  <Badge variant={plan.enabled ? "default" : "secondary"} className="text-[10px]">
                    {plan.enabled ? t.transactions.running : t.transactions.paused}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="pb-3">
                <div className="grid grid-cols-2 gap-1 text-xs text-muted-foreground mb-3">
                  <span>{t.transactions.perRun} {money(plan.amount)}</span>
                  <span>{cadenceDesc(plan)}</span>
                  {plan.next_run && <span>{t.transactions.nextRun}: {plan.next_run}</span>}
                  {plan.last_run && <span>{t.transactions.lastRun}: {plan.last_run}</span>}
                </div>
                <div className="flex flex-wrap gap-1.5">
                  <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => openEdit(plan)}>
                    <Pencil className="mr-1 h-3 w-3" /> {t.common.edit}
                  </Button>
                  <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => handleToggle(plan)}>
                    {plan.enabled ? t.transactions.pause : t.common.enable}
                  </Button>
                  <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => handleExecute(plan)} disabled={executing === plan.id}>
                    <Loader2 className={cn("mr-1 h-3 w-3", executing === plan.id && "animate-spin")} />
                    {executing === plan.id ? t.transactions.executing : t.transactions.executeNow}
                  </Button>
                  <Button size="sm" variant="outline" className="h-7 text-xs text-loss-600 hover:text-loss-600" onClick={() => setDeleting(plan.id)}>
                    <Trash2 className="mr-1 h-3 w-3" /> {t.common.delete}
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(o) => { if (!o) setDeleting(null) }}
        title={t.transactions.deletePlanTitle}
        description={t.transactions.deletePlanDesc}
        onConfirm={() => { if (deleting !== null) handleDelete(deleting) }}
      />

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{editingPlan ? t.transactions.editPlan : t.transactions.addPlan}</DialogTitle>
            <DialogDescription>
              {t.transactions.planDialogDesc}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-1.5">
              <Label>{t.transactions.fundCode}</Label>
              <Input value={code} onChange={(e) => setCode(e.target.value)} placeholder={t.transactions.fundCodePlaceholder} />
            </div>
            <div className="space-y-1.5">
              <Label>{t.transactions.amountPerRunYuan}</Label>
              <Input type="number" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="1000" min="0" step="0.01" />
            </div>
            <div className="space-y-1.5">
              <Label>{t.transactions.cadence}</Label>
              <Select value={cadence} onChange={(e) => setCadence(e.target.value)}>
                <option value="daily">{t.transactions.everyTradingDay}</option>
                <option value="week">{t.transactions.weekly}</option>
                <option value="biweek">{t.transactions.biweekly}</option>
                <option value="month">{t.transactions.monthly}</option>
              </Select>
            </div>
            {cadence === "week" || cadence === "biweek" ? (
              <div className="space-y-1.5">
                <Label>{t.transactions.dayOfWeekLabel}</Label>
                <Select value={dayOfWeek} onChange={(e) => setDayOfWeek(e.target.value)}>
                  {t.transactions.weekdays.map((d, i) => (<option key={i} value={String(i)}>{d}</option>))}
                </Select>
              </div>
            ) : cadence === "month" ? (
              <div className="space-y-1.5">
                <Label>{t.transactions.dayOfMonthLabel}</Label>
                <Input type="number" value={dayOfMonth} onChange={(e) => setDayOfMonth(e.target.value)} min="1" max="31" />
              </div>
            ) : null}
            <div className="space-y-1.5">
              <Label>{t.common.channel}</Label>
              <Select value={channel} onChange={(e) => setChannel(e.target.value)}>
                <option value="">{t.transactions.notSpecified}</option>
                {channels.map((c) => (<option key={c} value={c}>{c}</option>))}
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>{t.common.note}</Label>
              <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder={t.transactions.autoInvest} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>{t.common.cancel}</Button>
            <Button onClick={handleSave} disabled={saving}>
              {saving ? t.transactions.saving : t.common.save}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
