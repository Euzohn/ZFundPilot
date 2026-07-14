import { useState, useEffect, useMemo, useCallback } from "react"
import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { FetchResult, Position } from "@/api/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import LogoSpinner from "@/components/LogoSpinner"
import { RefreshCw, CheckCircle2, XCircle, RotateCw, AlertTriangle } from "lucide-react"
import { navStr } from "@/lib/format"

export default function NavUpdate() {
  // 和持仓页同源：用 getPositions 取数据（含 latest_date / latest_nav）
  const { data: positions, loading, error, reload } = useApi<Position[]>(() => api.getPositions())
  const [updating, setUpdating] = useState(false)
  const [progress, setProgress] = useState(0)
  const [results, setResults] = useState<FetchResult[] | null>(null)

  const todayStr = new Date().toISOString().slice(0, 10)

  // 按基金代码合并（跨渠道），取 latest_date
  const rows = useMemo(() => {
    if (!positions) return []
    const merged: Record<string, { fund_code: string; fund_name: string; date: string | null; nav: number | null }> = {}
    for (const p of positions) {
      const m = merged[p.fund_code]
      if (!m) {
        merged[p.fund_code] = {
          fund_code: p.fund_code,
          fund_name: p.fund_name || p.fund_code,
          date: p.latest_date,
          nav: p.latest_nav,
        }
      } else {
        // 取最新的日期
        if (p.latest_date && (!m.date || p.latest_date > m.date)) {
          m.date = p.latest_date
          m.nav = p.latest_nav
        }
      }
    }
    return Object.values(merged)
  }, [positions])

  // 需要更新的基金：无净值数据 或 最新净值日期 < 今天
  const needsUpdate = useMemo(() => {
    return rows.filter((r) => !r.date || r.date < todayStr).length
  }, [rows, todayStr])

  // 最近更新日期：所有基金中最新净值日期的最大值
  const lastUpdateDate = useMemo(() => {
    if (rows.length === 0) return ""
    let max = ""
    for (const r of rows) {
      if (r.date && r.date > max) max = r.date
    }
    return max
  }, [rows])

  // 页面获得焦点时自动刷新
  const handleVisibilityChange = useCallback(() => {
    if (document.visibilityState === "visible") {
      reload()
    }
  }, [reload])

  useEffect(() => {
    document.addEventListener("visibilitychange", handleVisibilityChange)
    return () => document.removeEventListener("visibilitychange", handleVisibilityChange)
  }, [handleVisibilityChange])

  const handleUpdate = async () => {
    setUpdating(true)
    setProgress(0)
    setResults(null)
    try {
      const res = await api.updateNav()
      setResults(res)
      setProgress(100)
      await reload()
    } catch (e) {
      alert(`更新失败: ${e}`)
    } finally {
      setUpdating(false)
    }
  }

  const okCount = results?.filter((r) => r.ok).length ?? 0
  const failCount = results?.filter((r) => !r.ok).length ?? 0

  // 合并更新结果
  const displayRows = useMemo(() => {
    if (results) {
      return rows.map((r) => {
        const u = results.find((r2) => r2.fund_code === r.fund_code)
        return { ...r, hasResult: !!u, ok: u?.ok, message: u?.message ?? "" }
      })
    }
    return rows.map((r) => ({ ...r, hasResult: false, ok: undefined, message: "" }))
  }, [rows, results])

  // 排序：待更新在前（无净值 > 净值过时），已更新在后
  const sortedRows = useMemo(() => {
    return [...displayRows].sort((a, b) => {
      const aNeeds = !a.date || a.date < todayStr ? 0 : 1
      const bNeeds = !b.date || b.date < todayStr ? 0 : 1
      if (aNeeds !== bNeeds) return aNeeds - bNeeds
      if (!a.date && !b.date) return a.fund_code.localeCompare(b.fund_code)
      if (!a.date) return -1
      if (!b.date) return 1
      if (a.date !== b.date) return a.date < b.date ? -1 : 1
      return a.fund_code.localeCompare(b.fund_code)
    })
  }, [displayRows, todayStr])

  return (
    <div className="space-y-6">
      <h1 className="text-xl md:text-2xl font-bold">净值更新</h1>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 md:gap-4">
        <Card>
          <CardContent className="flex items-center justify-between p-4 md:p-6">
            <div>
              <p className="text-sm text-muted-foreground">基金总数</p>
              <p className="text-xl md:text-2xl font-bold">{rows.length} 只</p>
            </div>
            <RefreshCw className="h-8 w-8 text-blue-500" />
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center justify-between p-4 md:p-6">
            <div>
              <p className="text-sm text-muted-foreground">待更新基金数</p>
              <p className="text-xl md:text-2xl font-bold">
                <span className={needsUpdate > 0 ? "text-amber-500" : "text-green-600"}>{needsUpdate}</span>
                <span className="text-base text-muted-foreground"> / {rows.length}</span>
              </p>
            </div>
            <AlertTriangle className={`h-8 w-8 ${needsUpdate > 0 ? "text-amber-400" : "text-green-400"}`} />
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 md:p-6">
            <p className="text-sm text-muted-foreground">净值最近更新</p>
            <p className="text-xl md:text-2xl font-bold">
              {lastUpdateDate || "未更新"}
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              {lastUpdateDate === todayStr ? "✅ 已是最新" : lastUpdateDate ? "⚠️ 非最新" : ""}
            </p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">批量更新</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            数据源：AkShare 优先，失败自动切换天天基金。首次抓取较慢。
          </p>
          <Button onClick={handleUpdate} disabled={updating} className="w-full">
            <RefreshCw className={`mr-2 h-4 w-4 ${updating ? "animate-spin" : ""}`} />
            {updating ? "更新中..." : "更新全部基金净值"}
          </Button>

          {updating && (
            <div className="space-y-2">
              <Progress value={progress} />
              <p className="text-center text-sm text-muted-foreground">正在拉取净值数据...</p>
            </div>
          )}

          {results && (
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-4">
                <span className="flex items-center gap-1 text-green-600">
                  <CheckCircle2 className="h-4 w-4" /> 成功 {okCount} 只
                </span>
                {failCount > 0 && (
                  <span className="flex items-center gap-1 text-red-600">
                    <XCircle className="h-4 w-4" /> 失败 {failCount} 只
                  </span>
                )}
              </div>
              {failCount > 0 && (
                <div className="rounded-md border border-red-200 bg-red-50 p-3">
                  {results.filter((r) => !r.ok).map((r) => (
                    <p key={r.fund_code} className="text-sm text-red-700">
                      {r.fund_code}：{r.message}
                    </p>
                  ))}
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle className="text-base">
            各基金最新净值
            {results && <span className="text-sm text-muted-foreground font-normal ml-2">（更新结果）</span>}
          </CardTitle>
          <Button variant="outline" size="sm" onClick={() => reload()} className="h-8">
            <RotateCw className="mr-1 h-3.5 w-3.5" /> 刷新
          </Button>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex py-8 items-center justify-center"><LogoSpinner className="h-10 w-10" /></div>
          ) : error ? (
            <p className="py-8 text-center text-red-500">加载失败：{error}</p>
          ) : sortedRows.length === 0 ? (
            <p className="py-8 text-center text-muted-foreground">暂无基金数据，请先添加交易记录</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>基金名称</TableHead>
                  <TableHead>最新日期</TableHead>
                  <TableHead className="text-right">最新净值</TableHead>
                  <TableHead className="text-center">状态</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sortedRows.map((r) => {
                  const outdated = !r.date || r.date < todayStr
                  return (
                    <TableRow key={r.fund_code} className={outdated ? "bg-amber-50/40" : ""}>
                      <TableCell>
                        <div className="flex flex-col">
                          <span className="font-medium max-w-[160px] truncate" title={r.fund_name}>
                            {r.fund_name}
                          </span>
                          <span className="font-mono text-xs text-muted-foreground">{r.fund_code}</span>
                        </div>
                      </TableCell>
                      <TableCell className="tabular-nums">{r.date ?? "—"}</TableCell>
                      <TableCell className="text-right font-mono tabular-nums">{navStr(r.nav)}</TableCell>
                      <TableCell className="text-center">
                        {r.hasResult ? (
                          r.ok ? (
                            <span title="更新成功"><CheckCircle2 className="h-4 w-4 text-green-500 inline" /></span>
                          ) : (
                            <span title={r.message}><XCircle className="h-4 w-4 text-red-500 inline" /></span>
                          )
                        ) : !r.date ? (
                          <Badge variant="outline" className="text-amber-600 border-amber-300 bg-amber-50 text-[11px] px-1.5 py-0">
                            待更新
                          </Badge>
                        ) : outdated ? (
                          <Badge variant="outline" className="text-amber-600 border-amber-300 bg-amber-50 text-[11px] px-1.5 py-0">
                            过时
                          </Badge>
                        ) : (
                          <span title="已是最新"><CheckCircle2 className="h-4 w-4 text-green-500 inline" /></span>
                        )}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}