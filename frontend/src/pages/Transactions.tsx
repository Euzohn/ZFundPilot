import { useState, useEffect } from "react"
import { useSearchParams } from "react-router-dom"
import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { Transaction, CSVParseResult, FundMeta, Fund } from "@/api/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select } from "@/components/ui/select"
import { Badge } from "@/components/ui/badge"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { money } from "@/lib/format"
import { toast } from "sonner"
import { Search, Plus, Pencil, Trash2, Download, Upload, FileDown } from "lucide-react"
import { getChannels } from "@/lib/channels"

const ACTION_LABELS: Record<string, string> = { buy: "买入", sell: "卖出" }

export default function Transactions() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [activeTab, setActiveTab] = useState("form")
  const [editingTx, setEditingTx] = useState<Transaction | null>(null)
  const [listReloadKey, setListReloadKey] = useState(0)
  const [prefill, setPrefill] = useState<{ code: string; action: string } | null>(null)

  // 从 URL 参数消费预填数据（从持仓页跳转过来）
  useEffect(() => {
    const code = searchParams.get("code")
    const action = searchParams.get("action")
    if (code) {
      setPrefill({ code, action: action || "buy" })
      setActiveTab("form")
      setSearchParams({}, { replace: true })
    }
  }, [searchParams, setSearchParams])

  const handleEdit = (tx: Transaction) => {
    setEditingTx(tx)
    setPrefill(null)
    setActiveTab("form")
  }

  const handleFormDone = () => {
    setEditingTx(null)
    setPrefill(null)
    setListReloadKey((k) => k + 1)
  }

  return (
    <div className="space-y-6">
      <h1 className="text-xl md:text-2xl font-bold">交易管理</h1>
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="grid w-full grid-cols-3 sm:inline-flex sm:w-auto">
          <TabsTrigger value="form">单笔录入</TabsTrigger>
          <TabsTrigger value="list">交易流水</TabsTrigger>
          <TabsTrigger value="csv">CSV 导入/导出</TabsTrigger>
        </TabsList>
        <TabsContent value="form">
          <TransactionForm
            editingTx={editingTx}
            prefill={prefill}
            onPrefillConsumed={() => setPrefill(null)}
            onDone={handleFormDone}
          />
        </TabsContent>
        <TabsContent value="list">
          <TransactionList key={listReloadKey} onEdit={handleEdit} />
        </TabsContent>
        <TabsContent value="csv"><CSVImportExport /></TabsContent>
      </Tabs>
    </div>
  )
}

// ---------------------------------------------------------------------------
// 单笔录入 / 编辑
// ---------------------------------------------------------------------------
function TransactionForm({ editingTx, prefill, onPrefillConsumed, onDone }: {
  editingTx: Transaction | null
  prefill: { code: string; action: string } | null
  onPrefillConsumed: () => void
  onDone: () => void
}) {
  const [code, setCode] = useState("")
  const [meta, setMeta] = useState<FundMeta | null>(null)
  const [fetching, setFetching] = useState(false)
  const [action, setAction] = useState("buy")
  const [date, setDate] = useState("")
  const [channels] = useState<string[]>(() => getChannels())
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

  const isEditing = !!editingTx

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

    // 渠道：预设值走 select，非预设值走 customChannel
    if (editingTx.channel && channels.includes(editingTx.channel)) {
      setChannel(editingTx.channel)
      setCustomChannel("")
    } else {
      setChannel("其它")
      setCustomChannel(editingTx.channel ?? "")
    }

    // 备注：拆分 T+1确认 标记
    const noteStr = editingTx.note ?? ""
    const hasT1 = noteStr.includes("T+1确认")
    setAfterThree(hasT1)
    const cleanNote = noteStr
      .replace(/\s*\|\s*T\+1确认\s*$/, "")
      .replace(/^T\+1确认\s*$/, "")
      .trim()
    setNote(cleanNote)

    // 尝试回填基金信息
    if (editingTx.fund_code) {
      api.fetchFundMeta(editingTx.fund_code).then((m) => setMeta(m)).catch(() => {})
    }
  }, [editingTx])

  // 预填模式：从持仓页跳转过来，只回填代码 + 操作方向
  useEffect(() => {
    if (!prefill) return
    setCode(prefill.code)
    setAction(prefill.action)
    setAmount(""); setShares(""); setNav(""); setFee("0")
    setNote(""); setAfterThree(false); setCustomChannel("")
    setMeta(null)
    // 自动获取基金信息
    if (prefill.code.trim()) {
      setFetching(true)
      api.fetchFundMeta(prefill.code.trim())
        .then((m) => { setMeta(m); setFetching(false) })
        .catch(() => setFetching(false))
    }
    onPrefillConsumed()
  }, [prefill, onPrefillConsumed])

  // 自动查询日期对应净值
  useEffect(() => {
    if (!code.trim() || !date) return
    setNavLoading(true)
    setNavNotFound(false)
    api.getNavForDate(code.trim(), date)
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
  }, [code, date])

  // 买入：金额 - 手续费 → 份额；卖出：份额 × 净值 - 手续费 → 金额
  const a = parseFloat(amount) || 0
  const f = parseFloat(fee) || 0
  const n = parseFloat(nav) || 0
  const s = parseFloat(shares) || 0

  // 买入时自动算份额（只读显示）
  const autoShares = action === "buy" && a > 0 && n > 0 && a - f > 0
    ? ((a - f) / n).toFixed(2)
    : ""
  // 卖出时自动算金额（只读显示）
  const autoAmount = action === "sell" && s > 0 && n > 0
    ? (s * n - f).toFixed(2)
    : ""

  const handleFetchMeta = async () => {
    if (!code.trim()) { toast.warning("请先输入基金代码"); return }
    setFetching(true)
    try {
      const m = await api.fetchFundMeta(code.trim())
      setMeta(m)
      if (m.ok) toast.success(`已识别：${m.fund_name}（${m.fund_type}）`)
      else toast.error(`获取失败：${m.message}`)
    } catch (e) { toast.error(`请求失败: ${e}`) }
    finally { setFetching(false) }
  }

  const resetForm = () => {
    setCode(""); setMeta(null); setAction("buy"); setDate("")
    setAmount(""); setShares(""); setNav(""); setFee("0")
    setCustomChannel(""); setNote(""); setAfterThree(false)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!code.trim()) { toast.error("基金代码不能为空"); return }
    if (!date) { toast.error("请选择成交日期"); return }

    // 使用自动计算的结果
    const finalShares = action === "buy" ? (parseFloat(autoShares) || null) : (parseFloat(shares) || null)
    const finalAmount = action === "sell" ? (parseFloat(autoAmount) || null) : (parseFloat(amount) || null)
    const finalNav = parseFloat(nav) || null

    if (!finalAmount || !finalShares) {
      toast.error(action === "buy" ? "请填写金额和净值（或手动输入净值）" : "请填写份额和净值（或手动输入净值）")
      return
    }

    const payload = {
      fund_code: code.trim(), action, date,
      amount: finalAmount,
      shares: finalShares,
      nav: finalNav,
      fee: parseFloat(fee) || 0,
      channel: customChannel.trim() || channel,
      note: (note.trim() ? note.trim() + " | " : "") + (afterThree ? "T+1确认" : ""),
    }

    setSaving(true)
    try {
      if (isEditing && editingTx?.id) {
        await api.updateTransaction(editingTx.id, payload)
        toast.success(`${ACTION_LABELS[action]} ${code.trim()} 已更新`)
      } else {
        await api.addTransaction(payload)
        toast.success(`${ACTION_LABELS[action]} ${code.trim()} 已保存`)
      }
      resetForm()
      onDone()
    } catch (e) { toast.error(`保存失败: ${e}`) }
    finally { setSaving(false) }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">
          {isEditing ? `编辑交易 #${editingTx?.id}` : "单笔录入"}
        </CardTitle>
      </CardHeader>
      <CardContent>
        {/* Step 1: fund code */}
        <div className="mb-6">
          <Label className="mb-2 block">第一步：输入代码，自动获取基金信息</Label>
          <div className="flex gap-2">
            <Input value={code} onChange={(e) => setCode(e.target.value)} placeholder="如 011612" className="max-w-[200px]" />
            <Button type="button" variant="secondary" onClick={handleFetchMeta} disabled={fetching}>
              <Search className="mr-1 h-4 w-4" /> {fetching ? "查询中..." : "获取基金信息"}
            </Button>
          </div>
          {meta?.ok && <p className="mt-2 text-sm text-green-600">当前基金：{meta.fund_name}（{meta.fund_type}）{meta.sector ? ` 板块:${meta.sector}` : ""}</p>}
        </div>

        {/* Step 2: transaction details */}
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <Label className="mb-1.5 block">操作 *</Label>
              <Select value={action} onChange={(e) => setAction(e.target.value)}>
                <option value="buy">买入</option>
                <option value="sell">卖出</option>
              </Select>
            </div>
            <div>
              <Label className="mb-1.5 block">成交日期 *</Label>
              <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
              <p className="mt-1 text-xs text-muted-foreground">
                📍 15:00 前下单按当日净值确认（T日），15:00 后按下一交易日确认（T+1日）
              </p>
              <label className="mt-1 flex items-center gap-1.5 text-sm">
                <input type="checkbox" checked={afterThree} onChange={(e) => setAfterThree(e.target.checked)} className="rounded" />
                15:00 后下单
              </label>
            </div>
            <div>
              <Label className="mb-1.5 block">渠道</Label>
              <Select value={channel} onChange={(e) => setChannel(e.target.value)}>
                {channels.map((c) => <option key={c} value={c}>{c}</option>)}
              </Select>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            {action === "buy" ? (
              <>
                <div>
                  <Label className="mb-1.5 block">金额 *</Label>
                  <Input type="number" step="0.01" min="0" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="0.00" autoFocus={!isEditing} />
                  <p className="mt-1 text-xs text-muted-foreground">买入总金额（元），含手续费</p>
                </div>
                <div>
                  <Label className="mb-1.5 block">份额 <span className="text-xs text-blue-500">自动计算</span></Label>
                  <Input type="number" step="0.01" value={autoShares} readOnly className="bg-muted/50" placeholder="—" />
                  <p className="mt-1 text-xs text-muted-foreground">(金额 - 手续费) ÷ 净值</p>
                </div>
              </>
            ) : (
              <>
                <div>
                  <Label className="mb-1.5 block">份额 *</Label>
                  <Input type="number" step="0.01" min="0" value={shares} onChange={(e) => setShares(e.target.value)} placeholder="0.00" autoFocus={!isEditing} />
                  <p className="mt-1 text-xs text-muted-foreground">卖出的基金份额（份）</p>
                </div>
                <div>
                  <Label className="mb-1.5 block">金额 <span className="text-xs text-blue-500">自动计算</span></Label>
                  <Input type="number" step="0.01" value={autoAmount} readOnly className="bg-muted/50" placeholder="—" />
                  <p className="mt-1 text-xs text-muted-foreground">份额 × 净值 - 手续费</p>
                </div>
              </>
            )}
            <div>
              <Label className="mb-1.5 block">成交净值</Label>
              <Input
                type="number" step="0.0001" min="0" value={nav}
                onChange={(e) => { setNav(e.target.value); setNavNotFound(false) }}
                placeholder={navLoading ? "查询中..." : "0.0000"}
                className={navNotFound ? "border-amber-400" : ""}
              />
              <p className="mt-1 text-xs text-muted-foreground">
                {navLoading ? "正在查询..." : navNotFound ? "未找到净值，请手动输入或先更新净值" : "每份基金的成交价格"}
              </p>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <Label className="mb-1.5 block">手续费</Label>
              <Input type="number" step="0.01" min="0" value={fee} onChange={(e) => setFee(e.target.value)} />
            </div>
            <div>
              <Label className="mb-1.5 block">自定义渠道（可选，覆盖上面选择）</Label>
              <Input value={customChannel} onChange={(e) => setCustomChannel(e.target.value)} placeholder="如 招商银行" />
            </div>
          </div>

          <div>
            <Label className="mb-1.5 block">备注</Label>
            <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="可选" />
          </div>

          <div className="flex gap-2">
            <Button type="submit" disabled={saving} className="flex-1">
              {isEditing ? (
                <><Pencil className="mr-1 h-4 w-4" /> {saving ? "更新中..." : "更新交易"}</>
              ) : (
                <><Plus className="mr-1 h-4 w-4" /> {saving ? "保存中..." : "保存交易"}</>
              )}
            </Button>
            {isEditing && (
              <Button type="button" variant="outline" onClick={() => { resetForm(); onDone() }}>
                取消编辑
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
function TransactionList({ onEdit }: { onEdit: (tx: Transaction) => void }) {
  const { data: txs, loading, reload } = useApi<Transaction[]>(() => api.getTransactions())
  const [funds, setFunds] = useState<Record<string, Fund>>({})
  const [showClearConfirm, setShowClearConfirm] = useState(false)
  const [clearConfirmText, setClearConfirmText] = useState("")

  // Load fund names
  useApi(() => api.getFunds(), []).data?.forEach((f: Fund) => {
    if (!funds[f.fund_code]) setFunds((prev) => ({ ...prev, [f.fund_code]: f }))
  })

  if (loading) return <div className="py-8 text-center text-muted-foreground">加载中...</div>

  const handleDelete = async (id: number) => {
    try {
      await api.deleteTransaction(id)
      toast.success("已删除")
      reload()
    } catch (e) { toast.error(`删除失败: ${e}`) }
  }

  const handleClearAll = async () => {
    try {
      await api.deleteAllTransactions()
      toast.success("已清空全部交易")
      setShowClearConfirm(false)
      setClearConfirmText("")
      reload()
    } catch (e) { toast.error(`清空失败: ${e}`) }
  }

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle className="text-base">交易流水</CardTitle>
        <Button variant="destructive" size="sm" onClick={() => { setShowClearConfirm(true); setClearConfirmText("") }}>
          <Trash2 className="mr-1 h-4 w-4" /> 清空全部
        </Button>
      </CardHeader>
      <CardContent>
        {!txs || txs.length === 0 ? (
          <p className="py-8 text-center text-muted-foreground">暂无交易流水</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-16">ID</TableHead>
                <TableHead>日期</TableHead>
                <TableHead>操作</TableHead>
                <TableHead>代码</TableHead>
                <TableHead>名称</TableHead>
                <TableHead>渠道</TableHead>
                <TableHead className="text-right">金额</TableHead>
                <TableHead className="text-right">份额</TableHead>
                <TableHead className="text-right">净值</TableHead>
                <TableHead className="text-right">手续费</TableHead>
                <TableHead>备注</TableHead>
                <TableHead className="w-20">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {txs.map((t) => {
                const fund = funds[t.fund_code]
                return (
                  <TableRow key={t.id}>
                    <TableCell className="text-xs text-muted-foreground">{t.id}</TableCell>
                    <TableCell>{t.date}</TableCell>
                    <TableCell>
                      <Badge variant={t.action === "buy" ? "success" : "destructive"}>
                        {ACTION_LABELS[t.action] ?? t.action}
                      </Badge>
                    </TableCell>
                    <TableCell className="font-mono text-xs">{t.fund_code}</TableCell>
                    <TableCell>{fund?.fund_name ?? t.fund_code}</TableCell>
                    <TableCell>{t.channel || "未标注"}</TableCell>
                    <TableCell className="text-right tabular-nums">{t.amount ? money(t.amount) : "—"}</TableCell>
                    <TableCell className="text-right tabular-nums">{t.shares?.toFixed(2) ?? "—"}</TableCell>
                    <TableCell className="text-right tabular-nums">{t.nav?.toFixed(4) ?? "—"}</TableCell>
                    <TableCell className="text-right tabular-nums">{t.fee || "—"}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{t.note}</TableCell>
                    <TableCell>
                      <div className="flex gap-1">
                        <Button variant="ghost" size="icon" onClick={() => onEdit(t)}>
                          <Pencil className="h-4 w-4 text-blue-500" />
                        </Button>
                        <Button variant="ghost" size="icon" onClick={() => handleDelete(t.id!)}>
                          <Trash2 className="h-4 w-4 text-red-500" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        )}
        {txs && txs.length > 0 && <p className="mt-3 text-sm text-muted-foreground">共 {txs.length} 笔交易</p>}
      </CardContent>

      {/* 清空确认弹窗 */}
      {showClearConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setShowClearConfirm(false)}>
          <div className="w-full max-w-sm rounded-lg bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="text-base font-bold text-red-600">⚠️ 清空全部交易流水</h3>
            <p className="mt-2 text-sm text-muted-foreground">
              此操作将删除所有交易记录，<strong>不可撤销</strong>。
            </p>
            <p className="mt-3 text-sm text-muted-foreground">
              请输入 <code className="rounded bg-muted px-1.5 py-0.5 text-sm font-mono">确认清空</code> 以确认：
            </p>
            <Input
              value={clearConfirmText}
              onChange={(e) => setClearConfirmText(e.target.value)}
              placeholder="确认清空"
              className="mt-2"
              onKeyDown={(e) => { if (e.key === "Enter" && clearConfirmText === "确认清空") { e.preventDefault(); handleClearAll() } }}
              autoFocus
            />
            <div className="mt-4 flex gap-2">
              <Button variant="outline" className="flex-1" onClick={() => { setShowClearConfirm(false); setClearConfirmText("") }}>
                取消
              </Button>
              <Button variant="destructive" className="flex-1" disabled={clearConfirmText !== "确认清空"} onClick={handleClearAll}>
                确认清空
              </Button>
            </div>
          </div>
        </div>
      )}
    </Card>
  )
}

// ---------------------------------------------------------------------------
// CSV 导入/导出
// ---------------------------------------------------------------------------
function CSVImportExport() {
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
      if (result.transactions.length > 0) toast.success(`解析成功 ${result.transactions.length} 笔`)
      if (result.errors.length > 0) toast.warning(`${result.errors.length} 条提示/警告`)
    } catch (e) { toast.error(`解析失败: ${e}`) }
    finally { setParsing(false) }
  }

  const handleImport = async () => {
    if (!parseResult?.transactions.length) return
    setImporting(true)
    try {
      const res = await api.confirmImport(parseResult.transactions, clearExisting, fetchMeta)
      toast.success(`已导入 ${res.imported} 笔交易`)
      setParseResult(null)
    } catch (e) { toast.error(`导入失败: ${e}`) }
    finally { setImporting(false) }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader><CardTitle className="text-base">批量导入交易流水</CardTitle></CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            必填列：<code className="rounded bg-muted px-1">fund_code</code>、
            <code className="rounded bg-muted px-1">action</code>（买入/卖出）、
            <code className="rounded bg-muted px-1">date</code>；
            <code className="rounded bg-muted px-1">amount</code>/<code className="rounded bg-muted px-1">shares</code>/<code className="rounded bg-muted px-1">nav</code> 至少两项；支持中文表头。
          </p>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => api.downloadTemplate()}>
              <Download className="mr-1 h-4 w-4" /> 下载 CSV 模板
            </Button>
            <label className="inline-flex cursor-pointer items-center justify-center gap-2 rounded-md border border-input bg-background px-4 py-2 text-sm font-medium hover:bg-accent">
              <Upload className="h-4 w-4" /> {parsing ? "解析中..." : "上传 CSV 文件"}
              <input type="file" accept=".csv" className="hidden" onChange={(e) => handleFile(e.target.files?.[0])} />
            </label>
          </div>

          {/* Parse errors */}
          {parseResult?.errors && parseResult.errors.length > 0 && (
            <div className="rounded-md border border-amber-200 bg-amber-50 p-3">
              <p className="mb-1 text-sm font-medium text-amber-800">⚠️ {parseResult.errors.length} 条提示/警告</p>
              <ul className="space-y-0.5 text-xs text-amber-700">
                {parseResult.errors.map((e, i) => <li key={i}>{e}</li>)}
              </ul>
            </div>
          )}

          {/* Preview table */}
          {parseResult?.transactions && parseResult.transactions.length > 0 && (
            <div className="space-y-3">
              <p className="text-sm font-medium">解析成功 {parseResult.transactions.length} 笔，预览：</p>
              <div className="max-h-64 overflow-auto rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>代码</TableHead><TableHead>操作</TableHead><TableHead>日期</TableHead>
                      <TableHead className="text-right">金额</TableHead><TableHead className="text-right">份额</TableHead>
                      <TableHead className="text-right">净值</TableHead><TableHead>渠道</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {parseResult.transactions.map((t, i) => (
                      <TableRow key={i}>
                        <TableCell className="font-mono text-xs">{t.fund_code}</TableCell>
                        <TableCell><Badge variant={t.action === "buy" ? "success" : "destructive"}>{ACTION_LABELS[t.action] ?? t.action}</Badge></TableCell>
                        <TableCell>{t.date}</TableCell>
                        <TableCell className="text-right tabular-nums">{t.amount ? money(t.amount) : "—"}</TableCell>
                        <TableCell className="text-right tabular-nums">{t.shares?.toFixed(2) ?? "—"}</TableCell>
                        <TableCell className="text-right tabular-nums">{t.nav?.toFixed(4) ?? "—"}</TableCell>
                        <TableCell>{t.channel || "—"}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>

              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-4">
                <label className="flex items-center gap-2 text-sm">
                  <input type="radio" checked={!clearExisting} onChange={() => setClearExisting(false)} /> 追加到现有流水
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input type="radio" checked={clearExisting} onChange={() => setClearExisting(true)} /> 清空后重新导入
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={fetchMeta} onChange={(e) => setFetchMeta(e.target.checked)} /> 自动获取缺失基金信息
                </label>
              </div>

              <Button onClick={handleImport} disabled={importing}>
                <Upload className="mr-1 h-4 w-4" /> {importing ? "导入中..." : "确认导入"}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="text-base">导出交易流水</CardTitle></CardHeader>
        <CardContent>
          <Button variant="outline" onClick={() => api.exportCsv()}>
            <FileDown className="mr-1 h-4 w-4" /> 导出为 CSV
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}
