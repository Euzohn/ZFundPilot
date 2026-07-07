import { useState } from "react"
import { useApi } from "@/lib/useApi"
import { api } from "@/api/client"
import type { FetchResult, LatestNav, Fund } from "@/api/types"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Progress } from "@/components/ui/progress"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import LogoSpinner from "@/components/LogoSpinner"
import { RefreshCw, CheckCircle2, XCircle } from "lucide-react"
import { navStr } from "@/lib/format"

export default function NavUpdate() {
  const { data: navs, loading, reload } = useApi<LatestNav[]>(() => api.getLatestNavs())
  const { data: funds } = useApi<Fund[]>(() => api.getFunds(), [])
  const [updating, setUpdating] = useState(false)
  const [progress, setProgress] = useState(0)
  const [results, setResults] = useState<FetchResult[] | null>(null)

  const fundMap: Record<string, Fund> = {}
  funds?.forEach((f) => { fundMap[f.fund_code] = f })

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

  // 更新后优先用 results 展示（含最新净值），否则用 navs（数据库读取）
  const rows: { fund_code: string; date: string | null; nav: number | null; ok?: boolean }[] =
    results
      ? results.map((r) => ({ fund_code: r.fund_code, date: r.latest_date, nav: r.latest_nav, ok: r.ok }))
      : (navs ?? []).map((n) => ({ fund_code: n.fund_code, date: n.date, nav: n.nav }))

  return (
    <div className="space-y-6">
      <h1 className="text-xl md:text-2xl font-bold">净值更新</h1>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 md:gap-4">
        <Card>
          <CardContent className="flex items-center justify-between p-4 md:p-6">
            <div>
              <p className="text-sm text-muted-foreground">待更新基金数</p>
              <p className="text-xl md:text-2xl font-bold">{navs?.length ?? 0} 只</p>
            </div>
            <RefreshCw className="h-8 w-8 text-blue-500" />
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 md:p-6">
            <p className="text-sm text-muted-foreground">净值最近更新</p>
            <p className="text-xl md:text-2xl font-bold">
              {navs?.length ? navs[0].date : "未更新"}
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
        <CardHeader>
          <CardTitle className="text-base">
            各基金最新净值{results ? "（更新结果）" : ""}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading && !results ? (
            <div className="flex py-8 items-center justify-center"><LogoSpinner className="h-10 w-10" /></div>
          ) : rows.length === 0 ? (
            <p className="py-8 text-center text-muted-foreground">暂无净值数据，请先添加交易记录并点击上方更新</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>基金名称</TableHead>
                  <TableHead>最新日期</TableHead>
                  <TableHead className="text-right">最新净值</TableHead>
                  {results && <TableHead className="text-center">状态</TableHead>}
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((r) => {
                  const fund = fundMap[r.fund_code]
                  return (
                    <TableRow key={r.fund_code}>
                      <TableCell>
                        <div className="flex flex-col">
                          <span className="font-medium max-w-[160px] truncate" title={fund?.fund_name ?? r.fund_code}>
                            {fund?.fund_name ?? r.fund_code}
                          </span>
                          <span className="font-mono text-xs text-muted-foreground">{r.fund_code}</span>
                        </div>
                      </TableCell>
                      <TableCell className="tabular-nums">{r.date ?? "—"}</TableCell>
                      <TableCell className="text-right font-mono tabular-nums">{navStr(r.nav)}</TableCell>
                      {results && (
                        <TableCell className="text-center">
                          {r.ok ? (
                            <CheckCircle2 className="h-4 w-4 text-green-500 inline" />
                          ) : (
                            <XCircle className="h-4 w-4 text-red-500 inline" />
                          )}
                        </TableCell>
                      )}
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
